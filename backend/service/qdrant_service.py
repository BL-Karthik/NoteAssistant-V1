
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer

load_dotenv()

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")

COLLECTION_NAME = "note_chunks"
EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
VECTOR_SIZE = 384

client = None
embedding_model = None


# -----------------------------------
# INITIALIZE QDRANT
# -----------------------------------

def initialize_qdrant():
    global client, embedding_model

    if not QDRANT_URL or not QDRANT_API_KEY:
        raise RuntimeError("Qdrant credentials are missing")

    client = QdrantClient(
        url=QDRANT_URL,
        api_key=QDRANT_API_KEY,
        timeout=30
    )

    embedding_model = SentenceTransformer(EMBEDDING_MODEL)

    if not client.collection_exists(COLLECTION_NAME):
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(
                size=VECTOR_SIZE,
                distance=models.Distance.COSINE
            )
        )

    for field_name in [
        "document_id",
        "conversation_id",
        "type",
        "title"
    ]:
        client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
            wait=True
        )

    print("Qdrant connected successfully")
    print("Qdrant payload indexes verified successfully")


# -----------------------------------
# TEXT CHUNKING
# -----------------------------------

def chunk_text(text, chunk_size=800, overlap=120):

    text = text.strip()

    if not text:
        return []

    if overlap >= chunk_size:
        raise ValueError("Overlap must be smaller than chunk size")

    chunks = []
    start = 0

    while start < len(text):

        end = min(start + chunk_size, len(text))

        if end < len(text):

            split_position = text.rfind(" ", start, end)

            if split_position > start:
                end = split_position

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = end - overlap

    return chunks


# -----------------------------------
# NOTE STORAGE
# -----------------------------------

def _save_note(note_id, content, title, conversation_id):

    if client is None or embedding_model is None:
        raise RuntimeError("Qdrant is not initialized")

    vector = embedding_model.encode(
        "passage: " + content
    ).tolist()

    point_id = str(
        uuid.uuid5(uuid.NAMESPACE_DNS, str(note_id))
    )

    updated_at = datetime.now(timezone.utc).isoformat()

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "note_id": str(note_id),
                    "conversation_id": str(conversation_id),
                    "title": title,
                    "content": content,
                    "type": "note",
                    "updated_at": updated_at
                }
            )
        ],
        wait=True
    )

    return {
        "status": "stored",
        "note_id": str(note_id)
    }


def store_note(note_id, content, title, conversation_id):

    return _save_note(
        note_id,
        content,
        title,
        conversation_id
    )


def update_note(note_id, content, title, conversation_id):

    return _save_note(
        note_id,
        content,
        title,
        conversation_id
    )


# -----------------------------------
# DOCUMENT STORAGE
# -----------------------------------

def delete_document_chunks(document_id):

    if client is None:
        raise RuntimeError("Qdrant is not initialized")

    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(
                            value=str(document_id)
                        )
                    )
                ]
            )
        ),
        wait=True
    )


def store_document_chunks(
    document_id,
    content,
    filename,
    conversation_id
):

    if client is None or embedding_model is None:
        raise RuntimeError("Qdrant is not initialized")

    chunks = chunk_text(content)

    if not chunks:
        raise ValueError("No text available to store")

    updated_at = datetime.now(timezone.utc).isoformat()

    delete_document_chunks(document_id)

    vectors = embedding_model.encode(
        ["passage: " + chunk for chunk in chunks]
    ).tolist()

    points = []

    for index, (chunk, vector) in enumerate(zip(chunks, vectors)):

        point_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_DNS,
                f"{document_id}:{index}"
            )
        )

        points.append(
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "note_id": str(document_id),
                    "document_id": str(document_id),
                    "conversation_id": str(conversation_id),
                    "filename": filename,
                    "title": filename,
                    "content": chunk,
                    "chunk_index": index,
                    "type": "document",
                    "updated_at": updated_at
                }
            )
        )

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
        wait=True
    )

    return {
        "status": "stored",
        "document_id": str(document_id),
        "filename": filename,
        "total_chunks": len(chunks)
    }


# -----------------------------------
# FILTER HELPERS
# -----------------------------------

def build_conversation_filter(conversation_id):

    if not conversation_id:
        return None

    return models.Filter(
        must=[
            models.FieldCondition(
                key="conversation_id",
                match=models.MatchValue(
                    value=str(conversation_id)
                )
            )
        ]
    )


def build_search_filter(
    conversation_id=None,
    note_type=None,
    topic_name=None
):

    conditions = []

    if conversation_id:

        conditions.append(
            models.FieldCondition(
                key="conversation_id",
                match=models.MatchValue(
                    value=str(conversation_id)
                )
            )
        )

    if note_type:

        conditions.append(
            models.FieldCondition(
                key="type",
                match=models.MatchValue(
                    value=note_type
                )
            )
        )

    if topic_name:

        conditions.append(
            models.FieldCondition(
                key="title",
                match=models.MatchValue(
                    value=topic_name
                )
            )
        )

    if not conditions:
        return None

    return models.Filter(must=conditions)


# -----------------------------------
# GLOBAL TOPIC TITLE VALIDATION
# -----------------------------------

def is_valid_topic_title(title):

    if not title or not isinstance(title, str):
        return False

    normalized = " ".join(
        title.strip().lower().split()
    )

    if not normalized:
        return False

    invalid_exact_titles = {
        "test",
        "testing",
        "test message",
        "hello",
        "hi",
        "hey",
        "new conversation",
        "untitled"
    }

    if normalized in invalid_exact_titles:
        return False

    # Exclude greeting-style titles.
    if normalized.startswith((
        "hello ",
        "hello,",
        "hi ",
        "hi,",
        "hey ",
        "hey,"
    )):
        return False

    # Exclude test-message titles.
    if "test message" in normalized:
        return False

    return True


# -----------------------------------
# GLOBAL TOPIC LISTING
# -----------------------------------

def get_global_topics():

    """
    Retrieve unique meaningful global topic names.

    Only points with type='note' are included.

    Excludes:
    - Uploaded document chunks
    - Greetings
    - Test messages
    - Placeholder titles

    Returns one entry per unique topic title.
    """

    if client is None:
        raise RuntimeError("Qdrant client is not initialized")

    topic_filter = models.Filter(
        must=[
            models.FieldCondition(
                key="type",
                match=models.MatchValue(value="note")
            )
        ]
    )

    topics = {}
    next_offset = None

    while True:

        results, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=topic_filter,
            limit=256,
            offset=next_offset,
            with_payload=True,
            with_vectors=False
        )

        for point in results:

            payload = point.payload or {}

            title = payload.get("title")
            note_id = payload.get("note_id")
            content = payload.get("content", "")
            updated_at = payload.get("updated_at", "")

            if not note_id or not is_valid_topic_title(title):
                continue

            normalized_title = " ".join(
                title.strip().lower().split()
            )

            existing = topics.get(normalized_title)

            if (
                existing is None
                or updated_at > existing.get("updated_at", "")
            ):

                topics[normalized_title] = {
                    "title": title.strip(),
                    "note_id": note_id,
                    "content": content,
                    "conversation_id": payload.get(
                        "conversation_id"
                    ),
                    "updated_at": updated_at
                }

        if next_offset is None:
            break

    return sorted(
        topics.values(),
        key=lambda item: item["title"].lower()
    )


# -----------------------------------
# SEMANTIC SEARCH
# -----------------------------------

def search_notes(
    query,
    limit=5,
    conversation_id=None,
    note_type=None,
    topic_name=None
):

    """
    Semantic search with optional filters.

    Global topic notes:
        search_notes(query, note_type="note")

    Uploaded document chunks:
        search_notes(query, note_type="document")

    One selected global topic:
        search_notes(
            query,
            note_type="note",
            topic_name="Note Assistant Project"
        )
    """

    if client is None or embedding_model is None:
        raise RuntimeError("Qdrant is not initialized")

    if not query or not query.strip():
        return []

    if limit < 1:
        raise ValueError("Limit must be at least 1")

    vector = embedding_model.encode(
        "query: " + query.strip()
    ).tolist()

    query_filter = build_search_filter(
        conversation_id=conversation_id,
        note_type=note_type,
        topic_name=topic_name
    )

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        query_filter=query_filter,
        limit=limit,
        with_payload=True
    )

    search_results = []

    for point in results.points:

        payload = point.payload or {}

        search_results.append({
            "note_id": payload.get("note_id"),
            "document_id": payload.get("document_id"),
            "conversation_id": payload.get("conversation_id"),
            "title": payload.get("title", "Untitled"),
            "filename": payload.get("filename"),
            "content": payload.get("content", ""),
            "chunk_index": payload.get("chunk_index"),
            "type": payload.get("type", "note"),
            "updated_at": payload.get("updated_at"),
            "score": point.score
        })

    return search_results


# -----------------------------------
# GET LATEST UPLOADED DOCUMENTS
# -----------------------------------

def get_latest_documents(
    limit=2,
    conversation_id=None
):

    if client is None:
        raise RuntimeError("Qdrant client is not initialized.")

    if limit < 1:
        raise ValueError("Limit must be at least 1.")

    documents = {}
    next_offset = None

    document_conditions = [
        models.FieldCondition(
            key="type",
            match=models.MatchValue(value="document")
        )
    ]

    if conversation_id is not None:

        document_conditions.append(
            models.FieldCondition(
                key="conversation_id",
                match=models.MatchValue(
                    value=str(conversation_id)
                )
            )
        )

    document_filter = models.Filter(
        must=document_conditions
    )

    # Find documents belonging to this conversation.
    while True:

        results, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=document_filter,
            limit=256,
            offset=next_offset,
            with_payload=True,
            with_vectors=False
        )

        for point in results:

            payload = point.payload or {}

            document_id = payload.get("document_id")

            if not document_id:
                continue

            updated_at = payload.get("updated_at", "")

            if document_id not in documents:

                documents[document_id] = {
                    "document_id": document_id,
                    "filename": payload.get(
                        "filename",
                        "Unknown"
                    ),
                    "conversation_id": payload.get(
                        "conversation_id"
                    ),
                    "updated_at": updated_at
                }

            elif updated_at > documents[document_id]["updated_at"]:

                documents[document_id]["updated_at"] = updated_at

        if next_offset is None:
            break

    latest_documents = sorted(
        documents.values(),
        key=lambda item: item["updated_at"],
        reverse=True
    )[:limit]

    complete_documents = []

    # Retrieve all chunks for each selected document.
    for document in latest_documents:

        chunks = []
        next_chunk_offset = None

        chunk_conditions = [
            models.FieldCondition(
                key="document_id",
                match=models.MatchValue(
                    value=document["document_id"]
                )
            ),
            models.FieldCondition(
                key="type",
                match=models.MatchValue(value="document")
            )
        ]

        if conversation_id is not None:

            chunk_conditions.append(
                models.FieldCondition(
                    key="conversation_id",
                    match=models.MatchValue(
                        value=str(conversation_id)
                    )
                )
            )

        chunk_filter = models.Filter(
            must=chunk_conditions
        )

        while True:

            results, next_chunk_offset = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=chunk_filter,
                limit=256,
                offset=next_chunk_offset,
                with_payload=True,
                with_vectors=False
            )

            for point in results:

                payload = point.payload or {}

                chunks.append({
                    "chunk_index": payload.get(
                        "chunk_index",
                        0
                    ),
                    "content": payload.get("content", "")
                })

            if next_chunk_offset is None:
                break

        chunks.sort(
            key=lambda item: item["chunk_index"]
        )

        document_text = "\n".join(
            chunk["content"]
            for chunk in chunks
            if chunk["content"]
        )

        complete_documents.append({
            **document,
            "content": document_text,
            "total_chunks": len(chunks)
        })

    return complete_documents
