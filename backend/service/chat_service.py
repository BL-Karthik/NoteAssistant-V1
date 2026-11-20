
import re

from service.note_assistant import (
    analyze_message,
    generate_search_query,
    extract_global_memories
)

from service.document_compare import (
    compare_documents
)

from service.qdrant_service import (
    store_note,
    update_note,
    search_notes,
    get_latest_documents,
    get_global_topics
)

from service.conversation_service import (
    update_conversation_title_if_default,
    save_global_memory,
    get_global_memories
)


SIMILARITY_THRESHOLD = 0.80

CLARIFICATION_MARKER = (
    "I found several projects in your saved notes."
)


# -----------------------------------
# DOCUMENT COMPARISON DETECTION
# -----------------------------------

def is_document_comparison_request(messages, latest_message):

    message = latest_message.lower().strip()

    comparison_pattern = (
        r"\b(compare|comparison|compared|differences?|"
        r"similarities|contrast)\b"
    )

    if not re.search(comparison_pattern, message):
        return False

    temporal_pattern = (
        r"\b(yesterday|today|tomorrow|last week|"
        r"this week|last month|this month|"
        r"last year|this year|morning|evening)\b"
    )

    if re.search(temporal_pattern, message):
        return False

    document_pattern = (
        r"\b(documents?|docs?|files?|pdfs?|docx|"
        r"attachments?|uploaded|reports?|contracts?|"
        r"spreadsheets?|presentations?)\b"
    )

    if re.search(document_pattern, message):
        return True

    document_reference_pattern = (
        r"\b(compare these|compare those|compare both|"
        r"compare them|compare the two|compare latest two|"
        r"compare last two|compare the latest|"
        r"compare the last|compare both of them)\b"
    )

    if not re.search(document_reference_pattern, message):
        return False

    recent_messages = messages[-15:]

    document_context_pattern = (
        r"\b(document|pdf|docx|uploaded file|"
        r"attachment|report|contract|spreadsheet|"
        r"presentation|file upload)\b"
    )

    for previous_message in recent_messages:

        previous_content = previous_message.get(
            "content", ""
        ).lower()

        if re.search(
            document_context_pattern,
            previous_content
        ):
            return True

    return False


# -----------------------------------
# GLOBAL MEMORY RETRIEVAL
# -----------------------------------

def retrieve_global_memory_context():

    try:

        memories = get_global_memories(limit=100)

        print("\n========== GLOBAL MEMORIES ==========")
        print("Retrieved global memories:", len(memories))

        for memory in memories:

            print(
                memory.get("category"),
                "|",
                memory.get("memory_key"),
                "|",
                memory.get("memory_value")
            )

        print("=====================================\n")

        return memories

    except Exception as error:

        print("Global memory retrieval failed:", error)

        return []


# -----------------------------------
# GLOBAL MEMORY STORAGE
# -----------------------------------

def store_extracted_global_memories(
    user_message,
    conversation_id
):

    try:

        memories = extract_global_memories(user_message)

        if not memories:
            print("No new global memories extracted.")
            return 0

        saved_count = 0

        print("\n========== GLOBAL MEMORY EXTRACTION ==========")

        for memory in memories:

            try:

                save_global_memory(
                    category=memory["category"],
                    memory_key=memory["memory_key"],
                    memory_value=memory["memory_value"],
                    source_conversation_id=conversation_id
                )

                saved_count += 1

                print(
                    "Saved:",
                    memory["category"],
                    "|",
                    memory["memory_key"],
                    "|",
                    memory["memory_value"]
                )

            except Exception as error:

                print(
                    "Failed to save memory:",
                    memory.get("memory_key"),
                    error
                )

        print("Total saved:", saved_count)
        print("===============================================\n")

        return saved_count

    except Exception as error:

        print("Global memory extraction failed:", error)

        return 0


# -----------------------------------
# TOPIC MATCHING HELPERS
# -----------------------------------

def normalize_topic_name(topic_name):

    if not isinstance(topic_name, str):
        return ""

    return re.sub(
        r"\s+",
        " ",
        topic_name.strip().lower()
    )


def find_matching_global_topic(
    relevant_notes,
    topic_name
):

    normalized_topic = normalize_topic_name(topic_name)

    if not normalized_topic:
        return None

    matching_notes = []

    for note in relevant_notes:

        if note.get("type", "note") != "note":
            continue

        existing_title = normalize_topic_name(
            note.get("title", "")
        )

        similarity = note.get("score", 0)

        if existing_title != normalized_topic:
            continue

        if not isinstance(similarity, (int, float)):
            continue

        if similarity < SIMILARITY_THRESHOLD:
            continue

        if not note.get("note_id") or not note.get("content"):
            continue

        matching_notes.append(note)

    if not matching_notes:
        return None

    return max(
        matching_notes,
        key=lambda note: note["score"]
    )


# -----------------------------------
# VAGUE TOPIC REFERENCE DETECTION
# -----------------------------------

def is_vague_topic_reference(message):

    if not message:
        return False

    normalized = message.lower().strip()

    patterns = [
        r"\bcontinue (the |our |my )?(previous |earlier |old )?project\b",
        r"\bcontinue (the |our )?project we discussed\b",
        r"\bthe project we discussed earlier\b",
        r"\bthat project\b",
        r"\bprevious project\b",
        r"\bearlier project\b",
        r"\bcontinue our previous work\b",
        r"\bcontinue where we left off\b",
        r"\bresume (the |our |my )?(previous |earlier )?project\b",
        r"\bwhat project were we working on\b",
        r"\bwhich project were we discussing\b",
        r"\bcontinue our work from before\b"
    ]

    return any(
        re.search(pattern, normalized)
        for pattern in patterns
    )


# -----------------------------------
# CHECK FOR PENDING TOPIC CLARIFICATION
# -----------------------------------

def has_pending_topic_clarification(messages):

    for message in reversed(messages[:-1]):

        if message.get("role") != "assistant":
            continue

        content = message.get("content", "")

        if CLARIFICATION_MARKER in content:
            return True

        return False

    return False


# -----------------------------------
# RESOLVE USER TOPIC SELECTION
# -----------------------------------

def resolve_selected_topic(message, topics):

    if not message or not topics:
        return None

    normalized_message = normalize_topic_name(message)

    # Exact topic title.
    for topic in topics:

        title = topic.get("title", "")
        normalized_title = normalize_topic_name(title)

        if normalized_message == normalized_title:
            return topic

    # User selects by number.
    number_match = re.fullmatch(
        r"\s*(?:the\s*)?(\d{1,2})(?:st|nd|rd|th)?\s*\.?\s*",
        normalized_message
    )

    if number_match:

        selected_number = int(number_match.group(1))

        if 1 <= selected_number <= len(topics):
            return topics[selected_number - 1]

    ordinal_map = {
        "first": 1,
        "1st": 1,
        "second": 2,
        "2nd": 2,
        "third": 3,
        "3rd": 3,
        "fourth": 4,
        "4th": 4,
        "fifth": 5,
        "5th": 5
    }

    ordinal_match = re.search(
        r"\b(first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th)\b",
        normalized_message
    )

    if ordinal_match:

        selected_number = ordinal_map[ordinal_match.group(1)]

        if 1 <= selected_number <= len(topics):
            return topics[selected_number - 1]

    # Allow a clear topic title within a longer selection message.
    matching_topics = []

    for topic in topics:

        title = normalize_topic_name(
            topic.get("title", "")
        )

        if title and title in normalized_message:
            matching_topics.append(topic)

    if len(matching_topics) == 1:
        return matching_topics[0]

    return None


# -----------------------------------
# BUILD TOPIC CLARIFICATION RESPONSE
# -----------------------------------

def build_topic_clarification(topics):

    lines = [
        CLARIFICATION_MARKER,
        "",
        "Which one would you like to continue?",
        ""
    ]

    for index, topic in enumerate(topics, start=1):

        lines.append(
            f"{index}. {topic['title']}"
        )

    lines.extend([
        "",
        "You can reply with the project name or its number."
    ])

    return "\n".join(lines)


# -----------------------------------
# GLOBAL TOPIC SEARCH
# -----------------------------------

def search_global_topic_notes(
    search_query,
    limit=5,
    topic_name=None
):

    return search_notes(
        query=search_query,
        limit=limit,
        note_type="note",
        topic_name=topic_name
    )


def search_uploaded_document_chunks(
    search_query,
    limit=5
):

    return search_notes(
        query=search_query,
        limit=limit,
        note_type="document"
    )


# -----------------------------------
# MERGE CONSOLIDATED NOTE CONTENT
# -----------------------------------

def merge_note_content(
    old_content,
    new_content
):

    old_content = (
        old_content.strip()
        if isinstance(old_content, str)
        else ""
    )

    new_content = (
        new_content.strip()
        if isinstance(new_content, str)
        else ""
    )

    if not new_content:
        return old_content

    if not old_content:
        return new_content

    # Gemini may return the entire consolidated note,
    # including the previous content.
    if old_content in new_content:
        return new_content

    # Avoid adding content that is already stored.
    if new_content in old_content:
        return old_content

    # For a normal incremental note, append the new content.
    return (
        old_content.rstrip()
        + "\n"
        + new_content
    )


# -----------------------------------
# PROCESS CHAT MESSAGE
# -----------------------------------

def process_chat_message(
    conversation_id,
    content,
    ai_messages,
    user_message
):

    """
    Process the latest user message.

    Responsibilities:
    1. Detect document comparison requests.
    2. Retrieve global memories.
    3. Identify ambiguous global topic references.
    4. Search global topic notes separately from documents.
    5. Analyze the message with Gemini.
    6. Handle incomplete-note clarification.
    7. Update conversation title.
    8. Extract global memories only when appropriate.
    9. Save or update worthy global topic notes.

    Session insertion and API response construction
    remain in indent.py.
    """

    # -----------------------------------
    # 1. DOCUMENT COMPARISON
    # -----------------------------------

    if is_document_comparison_request(
        ai_messages,
        content
    ):

        print("\n========== DOCUMENT COMPARISON ==========")
        print("Conversation ID:", conversation_id)
        print("User request:", content)

        latest_documents = get_latest_documents(
            limit=2,
            conversation_id=conversation_id
        )

        if len(latest_documents) < 2:

            response_text = (
                "I couldn't find two stored documents in this "
                "conversation to compare. Please upload another "
                "readable PDF, DOCX or TXT document."
            )

            compared_documents = []

        else:

            print("Documents selected:")

            for document in latest_documents:

                print(
                    document.get("filename"),
                    "| Chunks:",
                    document.get("total_chunks")
                )

            response_text = compare_documents(
                latest_documents
            )

            compared_documents = [
                {
                    "filename": document.get("filename"),
                    "total_chunks": document.get("total_chunks")
                }
                for document in latest_documents
            ]

        print("==========================================\n")

        return {
            "comparison": True,
            "response_text": response_text,
            "intent": "QUERY",
            "should_save": False,
            "needs_clarification": False,
            "title": "Document Comparison",
            "compared_documents": compared_documents,
            "qdrant_status": "skipped",
            "retrieved_notes": 0
        }

    # -----------------------------------
    # 2. RETRIEVE GLOBAL MEMORIES
    # -----------------------------------

    global_memories = retrieve_global_memory_context()

    # -----------------------------------
    # 3. LOAD GLOBAL TOPIC NAMES
    # -----------------------------------

    try:

        global_topics = get_global_topics()

        print("\n========== GLOBAL TOPICS ==========")

        for topic in global_topics:
            print("Topic:", topic.get("title"))

        print("Total global topics:", len(global_topics))
        print("===================================\n")

    except Exception as error:

        print("Global topic listing failed:", error)
        global_topics = []

    # -----------------------------------
    # 4. CHECK FOR PENDING TOPIC CLARIFICATION
    # -----------------------------------

    selected_topic = None

    pending_clarification = has_pending_topic_clarification(
        ai_messages
    )

    if pending_clarification:

        selected_topic = resolve_selected_topic(
            content,
            global_topics
        )

        if selected_topic is None:

            response_text = build_topic_clarification(
                global_topics
            )

            print(
                "Topic selection unclear. Asking user again."
            )

            return {
                "comparison": False,
                "response_text": response_text,
                "intent": "QUERY",
                "should_save": False,
                "needs_clarification": False,
                "title": "New Conversation",
                "topic_name": "",
                "topic_action": "UNKNOWN",
                "search_query": "",
                "qdrant_status": "skipped",
                "matched_note_id": None,
                "similarity_score": None,
                "retrieved_notes": 0,
                "global_memories_retrieved": len(global_memories),
                "global_memories_saved": 0
            }

        print(
            "User selected global topic:",
            selected_topic["title"]
        )

    # -----------------------------------
    # 5. DETECT AMBIGUOUS TOPIC REFERENCES
    # -----------------------------------

    elif is_vague_topic_reference(content):

        if len(global_topics) > 1:

            response_text = build_topic_clarification(
                global_topics
            )

            print(
                "Ambiguous project reference. "
                "Asking user to select a topic."
            )

            return {
                "comparison": False,
                "response_text": response_text,
                "intent": "QUERY",
                "should_save": False,
                "needs_clarification": False,
                "title": "New Conversation",
                "topic_name": "",
                "topic_action": "UNKNOWN",
                "search_query": "",
                "qdrant_status": "skipped",
                "matched_note_id": None,
                "similarity_score": None,
                "retrieved_notes": 0,
                "global_memories_retrieved": len(global_memories),
                "global_memories_saved": 0
            }

        if len(global_topics) == 1:
            selected_topic = global_topics[0]

    # -----------------------------------
    # 6. REWRITE SEARCH QUERY
    # -----------------------------------

    search_query = generate_search_query(
        messages=ai_messages,
        latest_message=content
    )

    if selected_topic:

        search_query = (
            selected_topic["title"] + " " + content
        )

    print("\n========== SEARCH QUERY REWRITING ==========")
    print("Original message:", content)
    print("Rewritten query:", search_query)
    print("=============================================\n")

    # -----------------------------------
    # 7. SEARCH GLOBAL TOPIC NOTES
    # -----------------------------------

    relevant_notes = search_global_topic_notes(
        search_query=search_query,
        limit=5,
        topic_name=(
            selected_topic["title"]
            if selected_topic
            else None
        )
    )

    # -----------------------------------
    # 8. SEARCH UPLOADED DOCUMENT CHUNKS
    # -----------------------------------

    relevant_documents = []

    if not selected_topic:

        relevant_documents = search_uploaded_document_chunks(
            search_query=search_query,
            limit=5
        )

    relevant_context = (
        relevant_notes + relevant_documents
    )

    print("\n========== GLOBAL TOPIC SEARCH RESULTS ==========")

    for note in relevant_notes:

        print("Title:", note.get("title"))
        print("Type:", note.get("type"))
        print("Similarity Score:", note.get("score"))
        print("-------------------------------------------")

    print("==================================================")

    print("\n========== DOCUMENT SEARCH RESULTS ==========")

    for document in relevant_documents:

        print("Filename:", document.get("filename"))
        print("Similarity Score:", document.get("score"))
        print("-------------------------------------------")

    print("=============================================\n")

    # -----------------------------------
    # 9. ANALYZE WITH GEMINI
    # -----------------------------------

    analysis = analyze_message(
        messages=ai_messages,
        relevant_notes=relevant_context,
        global_memories=global_memories
    )

    needs_clarification = (
        analysis.get("needs_clarification") is True
    )

    clarification_question = analysis.get(
        "clarification_question",
        ""
    )

    note_content = analysis.get(
        "note_content",
        ""
    )

    print("\n========== GEMINI ANALYSIS ==========")
    print("Intent:", analysis.get("intent"))
    print("Should save:", analysis.get("should_save"))
    print("Needs clarification:", needs_clarification)
    print("Clarification question:", clarification_question)
    print("Note content length:", len(note_content) if isinstance(note_content, str) else 0)
    print("=====================================\n")

    # -----------------------------------
    # 10. UPDATE CONVERSATION TITLE
    # -----------------------------------

    if analysis["title"] != "New Conversation":

        update_conversation_title_if_default(
            conversation_id,
            analysis["title"]
        )

    # -----------------------------------
    # 11. DETERMINE WHETHER NOTE CAN BE SAVED
    # -----------------------------------

    should_save = (
        analysis["intent"] == "NOTE"
        and analysis.get("should_save") is True
        and not needs_clarification
        and isinstance(note_content, str)
        and bool(note_content.strip())
    )

    # -----------------------------------
    # 12. EXTRACT GLOBAL MEMORIES
    # -----------------------------------

    global_memory_count = 0

    if needs_clarification:

        print("\n========== GLOBAL MEMORY EXTRACTION SKIPPED ==========")
        print(
            "A note is awaiting clarification. "
            "No potentially incomplete facts will be extracted."
        )
        print("======================================================\n")

    else:

        # When a note is complete, extract memories from
        # its consolidated content rather than just the
        # latest clarification answer.
        memory_source = (
            note_content.strip()
            if should_save
            else content
        )

        global_memory_count = store_extracted_global_memories(
            user_message=memory_source,
            conversation_id=conversation_id
        )

    # -----------------------------------
    # 13. SAVE OR UPDATE GLOBAL TOPIC NOTES
    # -----------------------------------

    qdrant_status = "skipped"
    matched_note_id = None
    similarity_score = None

    if needs_clarification:

        print("\n========== QDRANT SAVE SKIPPED ==========")
        print("Reason: Waiting for note clarification.")
        print("Clarification:", clarification_question)
        print("=========================================\n")

    elif should_save:

        topic_name = analysis.get("topic_name")

        if not isinstance(topic_name, str) or not topic_name.strip():

            topic_name = analysis.get(
                "title",
                "Untitled"
            )

        if not isinstance(topic_name, str) or not topic_name.strip():

            topic_name = "Untitled"

        topic_name = topic_name.strip()

        existing_note = find_matching_global_topic(
            relevant_notes=relevant_notes,
            topic_name=topic_name
        )

        if existing_note:

            merged_content = merge_note_content(
                old_content=existing_note["content"],
                new_content=note_content
            )

            update_note(
                note_id=existing_note["note_id"],
                content=merged_content,
                title=existing_note["title"],
                conversation_id=conversation_id
            )

            qdrant_status = "updated"
            matched_note_id = existing_note["note_id"]
            similarity_score = existing_note["score"]

            print("\n========== GLOBAL TOPIC UPDATED ==========")
            print("Topic:", topic_name)
            print("Note ID:", matched_note_id)
            print("Similarity:", similarity_score)
            print("===========================================\n")

        else:

            store_note(
                note_id=user_message["id"],
                content=note_content.strip(),
                title=topic_name,
                conversation_id=conversation_id
            )

            qdrant_status = "stored"

            print("\n========== GLOBAL TOPIC CREATED ==========")
            print("Topic:", topic_name)
            print("Note ID:", user_message["id"])
            print("==========================================\n")

    else:

        print("\n========== QDRANT SAVE SKIPPED ==========")
        print("Intent:", analysis["intent"])
        print("Should save:", analysis.get("should_save", False))
        print("Needs clarification:", needs_clarification)
        print("=========================================\n")

    # -----------------------------------
    # 14. RETURN CHAT RESULT
    # -----------------------------------

    return {
        "comparison": False,
        "response_text": analysis["response"],
        "intent": analysis["intent"],
        "should_save": should_save,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "title": analysis["title"],
        "topic_name": analysis["topic_name"],
        "topic_action": analysis["topic_action"],
        "search_query": search_query,
        "qdrant_status": qdrant_status,
        "matched_note_id": matched_note_id,
        "similarity_score": similarity_score,
        "retrieved_notes": len(relevant_context),
        "global_memories_retrieved": len(global_memories),
        "global_memories_saved": global_memory_count
    }
