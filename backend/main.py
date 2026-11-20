
import uuid
import asyncio
from copy import deepcopy
from contextlib import suppress
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from database import create_tables

from service.session_memory import (
    _sessions,
    get_session_count,
    add_message as add_session_message,
    get_messages as get_session_messages,
    get_inactive_sessions,
    mark_messages_saved,
    chat_request_lock
)

from service.conversation_service import (
    create_conversation,
    get_all_conversations,
    save_message,
    get_messages as get_database_messages,
    save_messages_batch
)

from service.chat_service import process_chat_message

from service.qdrant_service import (
    initialize_qdrant,
    store_document_chunks
)

from service.document_compare import summarize_document
from service.document_service import extract_text

from models.conversation_request import ConversationRequest
from models.message_request import MessageRequest
from models.chat_request import ChatRequest


app = FastAPI(
    title="Note Assistant",
    version="1.0.0"
)


MAX_UPLOAD_SIZE = 10 * 1024 * 1024

INACTIVITY_SECONDS = 120
SCHEDULER_INTERVAL_SECONDS = 15

scheduler_task = None

# Stores complete responses for replayed requests.
# This cache is in-memory and lasts until the backend restarts.
_chat_response_cache = {}

ALLOWED_FILE_TYPES = {
    ".pdf": ["application/pdf"],
    ".docx": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ],
    ".txt": ["text/plain"],
    ".png": ["image/png"],
    ".jpg": ["image/jpeg"],
    ".jpeg": ["image/jpeg"]
}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------
# AUTOMATIC POSTGRESQL BATCH SAVING
# -----------------------------------

async def save_inactive_sessions(
    inactivity_seconds=INACTIVITY_SECONDS
):
    inactive_sessions = get_inactive_sessions(
        inactivity_seconds=inactivity_seconds
    )

    if not inactive_sessions:
        return

    for session in inactive_sessions:

        conversation_id = session["conversation_id"]
        pending_messages = session["messages"]

        if not pending_messages:
            continue

        try:

            print("\n========== AUTOMATIC BATCH SAVE ==========")
            print("Conversation:", conversation_id)
            print("Pending messages:", len(pending_messages))

            database_messages = []

            for message in pending_messages:

                database_messages.append({
                    "client_message_id": message["client_message_id"],
                    "role": message["role"],
                    "content": message["content"],
                    "metadata": message.get("metadata") or {}
                })

            result = await asyncio.to_thread(
                save_messages_batch,
                conversation_id,
                database_messages
            )

            accepted_ids = result.get(
                "accepted_client_message_ids",
                []
            )

            marked_count = mark_messages_saved(
                conversation_id,
                accepted_ids
            )

            print("Database accepted:", len(accepted_ids))
            print("Marked as saved:", marked_count)
            print("==========================================\n")

        except Exception as error:

            print(
                "AUTOMATIC BATCH SAVE FAILED:",
                conversation_id,
                error
            )


async def batch_save_scheduler():

    print("Automatic PostgreSQL batch scheduler started")

    while True:

        try:
            await save_inactive_sessions()

        except asyncio.CancelledError:
            raise

        except Exception as error:
            print("BATCH SCHEDULER ERROR:", error)

        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


# -----------------------------------
# STARTUP
# -----------------------------------

@app.on_event("startup")
async def startup_event():

    global scheduler_task

    create_tables()
    initialize_qdrant()

    scheduler_task = asyncio.create_task(
        batch_save_scheduler()
    )

    print("PostgreSQL and Qdrant initialized successfully")
    print("Backend in-memory session storage is ready")
    print("Automatic batch saving: 2 minutes of inactivity")
    print("Scheduler interval: 15 seconds")


# -----------------------------------
# SHUTDOWN
# -----------------------------------

@app.on_event("shutdown")
async def shutdown_event():

    global scheduler_task

    if scheduler_task:

        scheduler_task.cancel()

        with suppress(asyncio.CancelledError):
            await scheduler_task

    print("Flushing pending messages before shutdown...")

    try:
        await save_inactive_sessions(inactivity_seconds=0)

    except Exception as error:
        print("SHUTDOWN MESSAGE SAVE FAILED:", error)

    print("Batch scheduler stopped")


# -----------------------------------
# HEALTH CHECK
# -----------------------------------

@app.get("/health")
def health_check():

    return {
        "status": "healthy",
        "service": "Note Assistant Backend",
        "session_storage": "in-memory",
        "automatic_batch_save": True,
        "inactivity_seconds": INACTIVITY_SECONDS,
        "scheduler_interval_seconds": SCHEDULER_INTERVAL_SECONDS
    }


# -----------------------------------
# SESSION HISTORY HELPERS
# -----------------------------------

def normalize_request_history(request_history):

    normalized_messages = []

    for message in request_history or []:

        if hasattr(message, "model_dump"):
            message = message.model_dump()

        elif hasattr(message, "dict"):
            message = message.dict()

        if not isinstance(message, dict):
            continue

        role = message.get("role")
        content = message.get("content", "")

        if role not in ["user", "assistant"]:
            continue

        if not isinstance(content, str) or not content.strip():
            continue

        normalized_messages.append({
            "role": role,
            "content": content.strip(),
            "client_message_id": (
                message.get("client_message_id")
                or message.get("id")
            ),
            "metadata": message.get("metadata") or {}
        })

    return normalized_messages


def initialize_session_from_history(
    conversation_id,
    request_history
):

    existing_messages = get_session_messages(conversation_id)

    if existing_messages:
        return existing_messages

    normalized_history = normalize_request_history(
        request_history
    )

    restored_from_database = False

    if not normalized_history:

        try:

            database_messages = get_database_messages(
                conversation_id
            )

            normalized_history = normalize_request_history(
                database_messages
            )

            restored_from_database = True

            print(
                "Restored session from PostgreSQL:",
                len(normalized_history),
                "messages"
            )

        except Exception as error:

            print("Session restoration failed:", error)
            normalized_history = []

    for message in normalized_history:

        add_session_message(
            conversation_id=conversation_id,
            role=message["role"],
            content=message["content"],
            metadata=message.get("metadata"),
            client_message_id=message.get("client_message_id"),
            saved=restored_from_database
        )

    return get_session_messages(conversation_id)


def add_user_message_to_session(
    conversation_id,
    content,
    client_message_id=None,
    metadata=None
):
    """
    Add a user message unless its exact message ID
    already exists.

    Same text with a different ID is a new message.
    """

    messages = get_session_messages(conversation_id)

    if client_message_id:

        existing_message = next(
            (
                message for message in messages
                if message.get("client_message_id") == client_message_id
            ),
            None
        )

        if existing_message:
            return messages

    add_session_message(
        conversation_id=conversation_id,
        role="user",
        content=content,
        metadata=metadata,
        client_message_id=client_message_id
    )

    return get_session_messages(conversation_id)


def find_existing_assistant_response(
    session_history,
    user_message_id
):
    """
    Find an assistant response occurring after
    the specified user message ID.
    """

    for index, message in enumerate(session_history):

        if (
            message.get("role") == "user"
            and message.get("client_message_id") == user_message_id
        ):

            for following_message in session_history[index + 1:]:

                if following_message.get("role") == "assistant":
                    return following_message

                if following_message.get("role") == "user":
                    break

    return None


def build_duplicate_response(
    conversation_id,
    user_message,
    assistant_message
):
    """
    Fallback response when the original full API response
    is unavailable, for example after a backend restart.
    """

    return {
        "conversation_id": conversation_id,
        "intent": "DUPLICATE_REQUEST",
        "title": "Previously processed message",
        "topic_name": None,
        "topic_action": None,
        "search_query": None,
        "qdrant_status": None,
        "matched_note_id": None,
        "similarity_score": None,
        "retrieved_notes": [],
        "global_memories_retrieved": [],
        "global_memories_saved": [],
        "user_message": user_message,
        "assistant_message": assistant_message,
        "duplicate": True
    }


# -----------------------------------
# TEMPORARY MESSAGE HELPER
# -----------------------------------

def create_temporary_message(
    conversation_id,
    role,
    content,
    metadata=None,
    client_message_id=None
):

    message_id = client_message_id or str(uuid.uuid4())

    return {
        "id": message_id,
        "client_message_id": message_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat()
    }


# -----------------------------------
# DOCUMENT UPLOAD
# -----------------------------------

@app.post("/conversations/{conversation_id}/upload")
async def upload_file(
    conversation_id: str,
    file: UploadFile = File(...)
):

    try:

        if not file.filename:
            raise HTTPException(
                status_code=400,
                detail="No file selected"
            )

        original_filename = file.filename
        filename = original_filename.lower()

        extension = (
            "." + filename.rsplit(".", 1)[-1]
            if "." in filename
            else ""
        )

        if extension not in ALLOWED_FILE_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Allowed: PDF, DOCX, TXT, PNG, JPG."
            )

        content_type = file.content_type
        allowed_mime_types = ALLOWED_FILE_TYPES[extension]

        if (
            content_type not in allowed_mime_types
            and content_type != "application/octet-stream"
        ):
            raise HTTPException(
                status_code=400,
                detail="File content type does not match the file extension."
            )

        file_content = await file.read(MAX_UPLOAD_SIZE + 1)

        if not file_content:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty"
            )

        if len(file_content) > MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail="File size cannot exceed 10 MB"
            )

        if extension in [".png", ".jpg", ".jpeg"]:

            return {
                "message": "Image received successfully",
                "conversation_id": conversation_id,
                "filename": original_filename,
                "content_type": content_type,
                "file_size": len(file_content),
                "status": "received",
                "note": "Image understanding is not implemented yet."
            }

        print("\n========== DOCUMENT DEBUG ==========")
        print("Filename:", original_filename)
        print("File size:", len(file_content))
        print("First 4 bytes:", file_content[:4])
        print("Extraction function:", extract_text.__code__.co_filename)

        extracted_text = extract_text(
            file_content,
            original_filename
        )

        print("Extracted text length:", len(extracted_text))
        print("Extracted text preview:", extracted_text[:300])
        print("====================================\n")

        if not extracted_text or not extracted_text.strip():
            raise HTTPException(
                status_code=400,
                detail="No readable text was extracted from this document."
            )

        document_id = str(uuid.uuid4())

        storage_result = store_document_chunks(
            document_id=document_id,
            content=extracted_text,
            filename=original_filename,
            conversation_id=conversation_id
        )

        summary = summarize_document(
            filename=original_filename,
            extracted_text=extracted_text
        )

        document_metadata = {
            "type": "document",
            "document_id": document_id,
            "filename": original_filename,
            "content_type": content_type,
            "file_size": len(file_content),
            "total_chunks": storage_result["total_chunks"]
        }

        stored_summary = add_session_message(
            conversation_id=conversation_id,
            role="assistant",
            content=summary,
            metadata=document_metadata
        )

        try:

            database_result = await asyncio.to_thread(
                save_messages_batch,
                conversation_id,
                [{
                    "client_message_id": stored_summary["client_message_id"],
                    "role": "assistant",
                    "content": summary,
                    "metadata": document_metadata
                }]
            )

            accepted_ids = database_result.get(
                "accepted_client_message_ids",
                []
            )

            mark_messages_saved(
                conversation_id,
                accepted_ids
            )

            print(
                "Document summary PostgreSQL save:",
                "successful" if stored_summary["client_message_id"] in accepted_ids
                else "not acknowledged"
            )

        except Exception as database_error:

            print(
                "DOCUMENT SUMMARY SAVE FAILED; "
                "MESSAGE REMAINS PENDING:",
                database_error
            )

        assistant_message = create_temporary_message(
            conversation_id=conversation_id,
            role="assistant",
            content=summary,
            metadata=document_metadata,
            client_message_id=stored_summary["client_message_id"]
        )

        return {
            "message": "Document processed successfully",
            "conversation_id": conversation_id,
            "document_id": document_id,
            "filename": original_filename,
            "content_type": content_type,
            "file_size": len(file_content),
            "text_length": len(extracted_text),
            "total_chunks": storage_result["total_chunks"],
            "status": "stored",
            "summary": summary,
            "assistant_message": assistant_message
        }

    except HTTPException:
        raise

    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))

    finally:
        await file.close()


# -----------------------------------
# CONVERSATIONS
# -----------------------------------

@app.post("/conversations")
def create_new_conversation(request: ConversationRequest):
    return create_conversation(request.title)


@app.get("/conversations")
def list_conversations():
    return get_all_conversations()


# -----------------------------------
# DIRECT MESSAGE SAVE
# -----------------------------------

@app.post("/conversations/{conversation_id}/messages")
def add_message(
    conversation_id: str,
    request: MessageRequest
):

    if request.role not in ["user", "assistant", "system"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid message role"
        )

    try:

        saved_message = save_message(
            conversation_id,
            request.role,
            request.content
        )

        if request.role in ["user", "assistant"]:

            add_session_message(
                conversation_id=conversation_id,
                role=request.role,
                content=request.content,
                saved=True
            )

        return saved_message

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# -----------------------------------
# GET CONVERSATION MESSAGES
# -----------------------------------

@app.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str):

    try:

        session_messages = get_session_messages(conversation_id)

        if session_messages:
            return session_messages

        return initialize_session_from_history(
            conversation_id,
            []
        )

    except Exception as error:

        print("MESSAGE RETRIEVAL ERROR:", error)

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# -----------------------------------
# CHAT
# -----------------------------------

@app.post("/conversations/{conversation_id}/chat")
def chat_with_assistant(
    conversation_id: str,
    request: ChatRequest
):

    content = request.content.strip()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )

    try:

        # -----------------------------------
        # 1. IDENTIFY FRONTEND MESSAGE ID
        # -----------------------------------

        request_history = getattr(request, "history", [])

        latest_user_id = None
        latest_user_metadata = {}

        for message in reversed(request_history or []):

            if hasattr(message, "model_dump"):
                message = message.model_dump()

            elif hasattr(message, "dict"):
                message = message.dict()

            if not isinstance(message, dict):
                continue

            message_content = message.get("content", "")

            if (
                message.get("role") == "user"
                and isinstance(message_content, str)
                and message_content.strip() == content
            ):

                latest_user_id = (
                    message.get("client_message_id")
                    or message.get("id")
                )

                latest_user_metadata = message.get("metadata") or {}
                break

        # Every request needs a message ID.
        # Reliable replay protection requires the frontend
        # to reuse this ID when retrying the same message.
        if not latest_user_id:
            latest_user_id = str(uuid.uuid4())

        cache_key = (conversation_id, latest_user_id)

        # -----------------------------------
        # 2. LOCK THIS SPECIFIC CHAT REQUEST
        # -----------------------------------

        with chat_request_lock(conversation_id, latest_user_id):

            # -----------------------------------
            # 3. INITIALIZE / RETRIEVE SESSION
            # -----------------------------------

            initialize_session_from_history(
                conversation_id,
                request_history
            )

            session_history = add_user_message_to_session(
                conversation_id,
                content,
                client_message_id=latest_user_id,
                metadata=latest_user_metadata
            )

            stored_user_message = next(
                (
                    message
                    for message in reversed(session_history)
                    if (
                        message.get("role") == "user"
                        and message.get("client_message_id") == latest_user_id
                    )
                ),
                None
            )

            if stored_user_message is None:
                raise RuntimeError(
                    "Unable to identify the latest user message in session."
                )

            user_message = create_temporary_message(
                conversation_id=conversation_id,
                role="user",
                content=stored_user_message["content"],
                metadata=stored_user_message.get("metadata"),
                client_message_id=stored_user_message["client_message_id"]
            )

            # -----------------------------------
            # 4. CHECK FOR AN ALREADY PROCESSED REQUEST
            # -----------------------------------

            cached_response = _chat_response_cache.get(cache_key)

            if cached_response is not None:

                print(
                    "DUPLICATE CHAT REQUEST DETECTED:",
                    latest_user_id
                )

                return deepcopy(cached_response)

            existing_assistant = find_existing_assistant_response(
                session_history,
                latest_user_id
            )

            if existing_assistant:

                print(
                    "EXISTING ASSISTANT RESPONSE FOUND:",
                    latest_user_id
                )

                assistant_message = create_temporary_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=existing_assistant["content"],
                    metadata=existing_assistant.get("metadata"),
                    client_message_id=existing_assistant["client_message_id"]
                )

                duplicate_response = build_duplicate_response(
                    conversation_id,
                    user_message,
                    assistant_message
                )

                return duplicate_response

            # -----------------------------------
            # 5. BUILD AI HISTORY
            # -----------------------------------

            ai_messages = [
                {
                    "role": message["role"],
                    "content": message["content"]
                }
                for message in session_history
            ]

            print("\n========== SESSION MEMORY ==========")
            print("Conversation ID:", conversation_id)
            print("User message ID:", latest_user_id)
            print("Messages in session:", len(ai_messages))

            for message in ai_messages:
                print(
                    message["role"],
                    ":",
                    message["content"][:150]
                )

            print("====================================\n")

            # -----------------------------------
            # 6. PROCESS CHAT USING CHAT SERVICE
            # -----------------------------------

            result = process_chat_message(
                conversation_id=conversation_id,
                content=content,
                ai_messages=ai_messages,
                user_message=user_message
            )

            response_text = result["response_text"]

            # -----------------------------------
            # 7. ADD ASSISTANT RESPONSE TO SESSION
            # -----------------------------------

            stored_assistant = add_session_message(
                conversation_id=conversation_id,
                role="assistant",
                content=response_text
            )

            assistant_message = create_temporary_message(
                conversation_id=conversation_id,
                role="assistant",
                content=response_text,
                client_message_id=stored_assistant["client_message_id"]
            )

            # -----------------------------------
            # 8. BUILD API RESPONSE
            # -----------------------------------

            if result.get("comparison"):

                api_response = {
                    "conversation_id": conversation_id,
                    "intent": result["intent"],
                    "title": result["title"],
                    "comparison": True,
                    "compared_documents": result["compared_documents"],
                    "qdrant_status": result["qdrant_status"],
                    "retrieved_notes": result["retrieved_notes"],
                    "user_message": user_message,
                    "assistant_message": assistant_message
                }

            else:

                api_response = {
                    "conversation_id": conversation_id,
                    "intent": result["intent"],
                    "title": result["title"],
                    "topic_name": result["topic_name"],
                    "topic_action": result["topic_action"],
                    "search_query": result["search_query"],
                    "qdrant_status": result["qdrant_status"],
                    "matched_note_id": result["matched_note_id"],
                    "similarity_score": result["similarity_score"],
                    "retrieved_notes": result["retrieved_notes"],
                    "global_memories_retrieved": result["global_memories_retrieved"],
                    "global_memories_saved": result["global_memories_saved"],

                    # New incomplete-note clarification fields.
                    "should_save": result["should_save"],
                    "needs_clarification": result["needs_clarification"],
                    "clarification_question": result["clarification_question"],

                    "user_message": user_message,
                    "assistant_message": assistant_message
                }

            # Keep the complete response for same-process retries.
            _chat_response_cache[cache_key] = deepcopy(api_response)

            return api_response

    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error))

    except Exception as error:

        print("CHAT ERROR:", error)

        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


# -----------------------------------
# DEBUG SESSION ENDPOINTS
# -----------------------------------

@app.get("/debug/sessions")
def debug_sessions():

    return {
        "total_sessions": get_session_count(),
        "conversation_ids": list(_sessions.keys())
    }


@app.get("/debug/sessions/{conversation_id}")
def debug_session(conversation_id: str):

    messages = get_session_messages(conversation_id)

    return {
        "conversation_id": conversation_id,
        "total_messages": len(messages),
        "messages": messages
    }


@app.get("/debug/sessions/{conversation_id}/pending")
def debug_pending_session(conversation_id: str):

    from service.session_memory import get_pending_messages

    messages = get_pending_messages(conversation_id)

    return {
        "conversation_id": conversation_id,
        "pending_count": len(messages),
        "pending_messages": messages
    }
