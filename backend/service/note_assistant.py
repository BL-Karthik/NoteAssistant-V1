
import json

from google.genai import types

from service.gemini_client import client, GEMINI_MODEL
from prompts.system_prompt import SYSTEM_PROMPT


# CONTEXT-AWARE SEARCH QUERY

def generate_search_query(messages, latest_message):

    original_query = latest_message.strip()

    if not original_query:
        return original_query

    if client is None:
        return original_query

    try:

        recent_messages = messages[-12:]

        conversation_context = []

        for message in recent_messages:

            role = message.get("role", "user")
            message_content = message.get("content", "")

            if role not in ["user", "assistant"]:
                continue

            if not message_content:
                continue

            conversation_context.append(
                f"{role.upper()}: {message_content}"
            )

        conversation_text = "\n".join(conversation_context)

        prompt = f"""
You rewrite user messages into standalone semantic
search queries for a vector database.

Use the conversation history to understand the latest
user message and create a query that retrieves the
correct notes or uploaded document chunks.

CONVERSATION HISTORY:
{conversation_text}

LATEST USER MESSAGE:
{original_query}

RULES:

1. Resolve references such as:
   "it", "that", "those", "the second issue",
   "the previous one", "that document" and "what about it".

2. Identify the correct project, document, topic or subject.

3. Preserve important names, dates and technical terms.

4. Convert vague follow-up questions into meaningful
   standalone search queries.

5. Do not invent facts.

6. Preserve clear standalone questions.

7. Do not answer the question.

8. Return only the rewritten search query.
"""

        result = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1
            )
        )

        rewritten_query = (result.text or "").strip()

        rewritten_query = (
            rewritten_query.strip('"').strip("'").strip()
        )

        return rewritten_query or original_query

    except Exception as error:

        print("Search query rewriting failed:", error)

        return original_query


# -----------------------------------
# BUILD NOTES AND DOCUMENT CONTEXT
# -----------------------------------

def build_notes_context(relevant_notes):

    if not relevant_notes:
        return ""

    note_context = []
    document_context = []

    for item in relevant_notes:

        item_type = item.get("type", "note")

        content = item.get("content", "")
        title = item.get("title", "Untitled")
        updated_at = item.get("updated_at", "Unknown")
        score = item.get("score", "Unknown")

        if not content:
            continue

        if item_type == "document":

            filename = item.get("filename", title)

            document_context.append(
                f"""
Filename: {filename}
Document ID: {item.get('document_id', 'Unknown')}
Chunk Number: {item.get('chunk_index', 'Unknown')}
Similarity Score: {score}
Extracted Content:
{content}
"""
            )

        else:

            note_context.append(
                f"""
Title: {title}
Last Updated: {updated_at}
Similarity Score: {score}
Content:
{content}
"""
            )

    context = ""

    if note_context:

        context += (
            "\n\nRELEVANT NOTES FROM LONG-TERM MEMORY:\n"
            + "\n".join(note_context)
        )

    if document_context:

        context += (
            "\n\nRELEVANT CONTENT FROM UPLOADED DOCUMENTS:\n"
            "Use filenames to identify their source. "
            "Do not mix unrelated documents.\n"
            + "\n".join(document_context)
        )

    return context


# -----------------------------------
# BUILD GLOBAL MEMORY CONTEXT
# -----------------------------------

def build_global_memory_context(global_memories):

    if not global_memories:
        return ""

    context = [
        "\n\nGLOBAL MEMORY FROM PREVIOUS CONVERSATIONS:",
        """
The following information was stored from previous
conversations.

Use relevant memories when answering the user.

Rules:
- Memories may come from different conversations.
- Do not assume every memory is relevant.
- Prefer the most recently updated reliable information.
- If two memories conflict, acknowledge the conflict.
- Do not invent missing information.
- Do not treat a memory as a new user message.
"""
    ]

    for memory in global_memories:

        category = memory.get("category", "general")
        memory_key = memory.get("memory_key", "")
        memory_value = memory.get("memory_value", "")
        updated_at = memory.get("updated_at", "Unknown")

        if not memory_key or not memory_value:
            continue

        context.append(
            f"""
Category: {category}
Memory Key: {memory_key}
Information: {memory_value}
Last Updated: {updated_at}
"""
        )

    return "\n".join(context)


# -----------------------------------
# CONVERSATION TITLE HELPERS
# -----------------------------------

def is_greeting_only(message):

    if not message:
        return True

    normalized = message.lower().strip()
    normalized = normalized.strip(".,!?;: ")

    greetings = {
        "hi",
        "hello",
        "hey",
        "hi there",
        "hello there",
        "hey there",
        "good morning",
        "good afternoon",
        "good evening",
        "how are you",
        "how are you doing",
        "what's up",
        "whats up"
    }

    return normalized in greetings


def get_first_meaningful_message(messages):

    for message in messages:

        if message.get("role") != "user":
            continue

        content = str(
            message.get("content", "")
        ).strip()

        if not content:
            continue

        if is_greeting_only(content):
            continue

        return content

    return ""


def create_fallback_title(message):

    if not message:
        return "New Conversation"

    title = message.splitlines()[0].strip()

    for separator in [". ", "? ", "! "]:

        if separator in title:

            title = title.split(
                separator, 1
            )[0].strip()

            break

    if len(title) > 60:

        shortened = title[:60].rsplit(
            " ", 1
        )[0].strip()

        title = shortened or title[:60].strip()

    if not title:
        return "New Conversation"

    return title[0].upper() + title[1:]


# -----------------------------------
# EXTRACT GLOBAL MEMORIES
# -----------------------------------

def extract_global_memories(user_message):

    if client is None:
        print("Global memory extraction skipped: Gemini unavailable.")
        return []

    if not user_message or not user_message.strip():
        return []

    prompt = f"""
You are a careful long-term memory extraction system.

Extract important information explicitly provided
or clearly confirmed by the user.

Possible memory categories:
- personal
- project
- preference
- decision
- task
- goal
- learning
- general

Examples:

"My project uses FastAPI and PostgreSQL."
=> project / backend_technology / FastAPI and PostgreSQL

"We decided to use Qdrant for vector search."
=> decision / vector_database / Qdrant

"I prefer step-by-step explanations."
=> preference / explanation_style / Step-by-step explanations

Do not save:
- Greetings.
- Ordinary questions.
- Temporary requests.
- Assistant-generated assumptions.
- Information not actually stated or confirmed.
- Repeated information without a meaningful update.
- Sensitive personal information.

Important:
- Extract only facts from the supplied user message.
- Do not infer personal facts from uploaded documents.
- Keep each memory concise and specific.
- Do not invent information.
- Return an empty list if no useful memory exists.

Return ONLY valid JSON:

{{
    "memories": [
        {{
            "category": "project",
            "memory_key": "backend_technology",
            "memory_value": "FastAPI and PostgreSQL"
        }}
    ]
}}

If no important information exists:

{{"memories": []}}

USER MESSAGE:
{user_message}
"""

    try:

        result = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )

        if not result.text:
            return []

        data = json.loads(result.text)

        memories = data.get("memories", [])

        if not isinstance(memories, list):
            return []

        valid_memories = []

        allowed_categories = {
            "personal",
            "project",
            "preference",
            "decision",
            "task",
            "goal",
            "learning",
            "general"
        }

        for memory in memories:

            if not isinstance(memory, dict):
                continue

            category = memory.get("category")
            memory_key = memory.get("memory_key")
            memory_value = memory.get("memory_value")

            if not all(
                isinstance(value, str) and value.strip()
                for value in (
                    category,
                    memory_key,
                    memory_value
                )
            ):
                continue

            category = category.strip().lower()
            memory_key = memory_key.strip()
            memory_value = memory_value.strip()

            if category not in allowed_categories:
                continue

            if len(memory_key) > 255:
                continue

            if len(memory_value) > 5000:
                continue

            valid_memories.append({
                "category": category,
                "memory_key": memory_key,
                "memory_value": memory_value
            })

        return valid_memories

    except Exception as error:

        print("Global memory extraction failed:", error)

        return []


# -----------------------------------
# ANALYZE MESSAGE
# -----------------------------------

def analyze_message(
    messages,
    relevant_notes=None,
    current_title=None,
    global_memories=None
):

    if client is None:

        raise RuntimeError(
            "GEMINI_API_KEY is missing. Configure it in your backend .env file."
        )

    context = build_notes_context(relevant_notes)

    global_context = build_global_memory_context(
        global_memories
    )

    system_prompt = (
        SYSTEM_PROMPT
        + context
        + global_context
    )

    contents = []

    for message in messages:

        role = message.get("role", "user")
        content = message.get("content", "")

        if role == "system":
            continue

        gemini_role = (
            "model" if role in ["assistant", "model"]
            else "user"
        )

        contents.append({
            "role": gemini_role,
            "parts": [
                {"text": str(content)}
            ]
        })

    try:

        result = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.2
            )
        )

        raw_content = result.text

        if not raw_content:

            raise RuntimeError(
                "Gemini returned an empty response."
            )

        analysis = json.loads(raw_content)

    except json.JSONDecodeError as error:

        raise RuntimeError(
            "Gemini returned an invalid JSON response."
        ) from error

    except Exception as error:

        raise RuntimeError(
            f"Gemini API request failed: {error}"
        ) from error

    if not isinstance(analysis, dict):

        raise RuntimeError(
            "AI response must be a JSON object"
        )

    # -----------------------------------
    # INTENT
    # -----------------------------------

    intent = str(
        analysis.get("intent", "CHAT")
    ).upper()

    if intent not in ["NOTE", "QUERY", "CHAT"]:
        intent = "CHAT"

    # -----------------------------------
    # CLARIFICATION DETECTION
    # -----------------------------------

    needs_clarification = (
        analysis.get("needs_clarification") is True
    )

    clarification_question = analysis.get(
        "clarification_question",
        ""
    )

    if not isinstance(clarification_question, str):
        clarification_question = ""

    clarification_question = (
        clarification_question.strip()
    )

    # -----------------------------------
    # NOTE-WORTHINESS
    # -----------------------------------

    should_save = (
        analysis.get("should_save") is True
    )

    if intent != "NOTE":
        should_save = False
        needs_clarification = False
        clarification_question = ""

    # Clarification must happen before saving.

    if needs_clarification:

        should_save = False

        if not clarification_question:
            needs_clarification = False

    # -----------------------------------
    # CONSOLIDATED NOTE CONTENT
    # -----------------------------------

    note_content = analysis.get(
        "note_content",
        ""
    )

    if not isinstance(note_content, str):
        note_content = ""

    note_content = note_content.strip()

    # A note must have actual content before saving.

    if should_save and not note_content:

        should_save = False

        print(
            "Note saving prevented: Gemini returned "
            "empty consolidated note content."
        )

    # Never return note content for a message that
    # must not be saved.

    if not should_save:
        note_content = ""

    # -----------------------------------
    # TOPIC ACTION
    # -----------------------------------

    topic_action = str(
        analysis.get("topic_action", "UNKNOWN")
    ).upper()

    allowed_actions = [
        "NEW_TOPIC",
        "CONTINUE_TOPIC",
        "SWITCH_TOPIC",
        "UNKNOWN"
    ]

    if topic_action not in allowed_actions:
        topic_action = "UNKNOWN"

    # -----------------------------------
    # TOPIC NAME
    # -----------------------------------

    topic_name = analysis.get("topic_name", "")

    if not isinstance(topic_name, str):
        topic_name = ""

    topic_name = topic_name.strip()[:100]

    # -----------------------------------
    # CONVERSATION TITLE
    # -----------------------------------

    first_meaningful_message = (
        get_first_meaningful_message(messages)
    )

    if (
        isinstance(current_title, str)
        and current_title.strip()
        and current_title.strip().lower() != "new conversation"
    ):

        title = current_title.strip()[:100]

    elif not first_meaningful_message:

        title = "New Conversation"

    else:

        title = analysis.get(
            "title",
            "New Conversation"
        )

        if not isinstance(title, str):
            title = "New Conversation"

        title = title.strip()

        invalid_titles = {
            "",
            "new conversation",
            "hi",
            "hello",
            "hey",
            "good morning",
            "good afternoon",
            "good evening"
        }

        if title.lower() in invalid_titles:

            title = create_fallback_title(
                first_meaningful_message
            )

        title = title[:100]

    # -----------------------------------
    # RESPONSE
    # -----------------------------------

    response_text = analysis.get(
        "response",
        "Could you tell me a little more?"
    )

    if not isinstance(response_text, str):
        response_text = "Could you tell me a little more?"

    response_text = response_text.strip()

    if not response_text:
        response_text = "Could you tell me a little more?"

    # Ensure the clarification question is actually
    # presented to the user.

    if needs_clarification:
        response_text = clarification_question

    # -----------------------------------
    # FINAL RESULT
    # -----------------------------------

    return {
        "intent": intent,
        "should_save": should_save,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "note_content": note_content,
        "title": title,
        "topic_name": topic_name,
        "topic_action": topic_action,
        "response": response_text
    }
