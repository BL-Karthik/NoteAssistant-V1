
import uuid

from psycopg.types.json import Jsonb

from database import get_connection

# ==========================================
# CONVERSATION MANAGEMENT
# ==========================================

def create_conversation(title="New Conversation"):
    conversation_id = str(uuid.uuid4())

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO conversations (conversation_id, title)
                VALUES (%s, %s)
                RETURNING conversation_id, title, created_at;
                """,
                (conversation_id, title)
            )
            row = cursor.fetchone()

    return {
        "id": row[0],
        "title": row[1],
        "created_at": row[2]
    }

def get_all_conversations():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT conversation_id, title, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC;
                """
            )
            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "title": row[1],
            "created_at": row[2],
            "updated_at": row[3]
        }
        for row in rows
    ]

def update_conversation_title_if_default(conversation_id, title):
    if not title or not title.strip():
        return

    title = title.strip()

    if title == "New Conversation":
        return

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE conversations
                SET title = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE conversation_id = %s
                  AND title = 'New Conversation';
                """,
                (title[:100], conversation_id)
            )

# ==========================================
# MESSAGE MANAGEMENT
# ==========================================

def save_message(conversation_id, role, content, metadata=None):
    """
    Save one message immediately.

    Kept for compatibility with existing endpoints.
    """

    message_metadata = metadata or {}

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO messages (
                    conversation_id,
                    role,
                    content,
                    metadata
                )
                VALUES (%s, %s, %s, %s)
                RETURNING message_id, conversation_id, role,
                          content, metadata, created_at;
                """,
                (
                    conversation_id,
                    role,
                    content,
                    Jsonb(message_metadata)
                )
            )

            message = cursor.fetchone()

            cursor.execute(
                """
                UPDATE conversations
                SET updated_at = CURRENT_TIMESTAMP
                WHERE conversation_id = %s;
                """,
                (conversation_id,)
            )

    return {
        "id": message[0],
        "conversation_id": message[1],
        "role": message[2],
        "content": message[3],
        "metadata": message[4] or {},
        "created_at": message[5]
    }

# ==========================================
# BATCH MESSAGE SAVING
# ==========================================

def save_messages_batch(conversation_id, messages):
    """
    Save multiple temporary session messages to PostgreSQL.

    Duplicate client_message_id values are ignored.
    """

    accepted_client_message_ids = []

    with get_connection() as connection:
        with connection.cursor() as cursor:

            # Verify conversation exists.
            cursor.execute(
                """
                SELECT conversation_id
                FROM conversations
                WHERE conversation_id = %s;
                """,
                (conversation_id,)
            )

            conversation = cursor.fetchone()

            if not conversation:
                raise ValueError("Conversation not found")

            for message in messages:

                client_message_id = message.get("client_message_id")
                role = message.get("role")
                content = message.get("content")
                metadata = message.get("metadata") or {}

                if not client_message_id:
                    raise ValueError("client_message_id is required")

                if role not in ("user", "assistant", "system"):
                    raise ValueError("Invalid message role")

                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Message content cannot be empty")

                if not isinstance(metadata, dict):
                    raise ValueError("Message metadata must be an object")

                cursor.execute(
                    """
                    INSERT INTO messages (
                        conversation_id,
                        client_message_id,
                        role,
                        content,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (
                        conversation_id,
                        client_message_id
                    )
                    WHERE client_message_id IS NOT NULL
                    DO NOTHING
                    RETURNING client_message_id;
                    """,
                    (
                        conversation_id,
                        client_message_id,
                        role,
                        content,
                        Jsonb(metadata)
                    )
                )

                inserted = cursor.fetchone()

                # Include the ID even when it was already saved.
                # This tells the frontend it can remove this ID
                # from its pending batch queue.
                accepted_client_message_ids.append(client_message_id)

            if accepted_client_message_ids:
                cursor.execute(
                    """
                    UPDATE conversations
                    SET updated_at = CURRENT_TIMESTAMP
                    WHERE conversation_id = %s;
                    """,
                    (conversation_id,)
                )

    return {
        "conversation_id": conversation_id,
        "accepted_client_message_ids": accepted_client_message_ids,
        "saved_count": len(accepted_client_message_ids)
    }

# ==========================================
# GET CONVERSATION MESSAGES
# ==========================================

def get_messages(conversation_id):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    message_id,
                    client_message_id,
                    role,
                    content,
                    metadata,
                    created_at
                FROM messages
                WHERE conversation_id = %s
                ORDER BY created_at ASC, message_id ASC;
                """,
                (conversation_id,)
            )

            rows = cursor.fetchall()

    return [
        {
            "id": row[0],
            "client_message_id": row[1],
            "role": row[2],
            "content": row[3],
            "metadata": row[4] or {},
            "created_at": row[5]
        }
        for row in rows
    ]

# ==========================================
# GLOBAL MEMORY MANAGEMENT
# ==========================================

def save_global_memory(
    category,
    memory_key,
    memory_value,
    source_conversation_id=None
):
    """
    Save or update information in shared global memory.

    Memories are independent of individual conversations.
    """

    category = category.strip().lower()
    memory_key = memory_key.strip()
    memory_value = memory_value.strip()

    if not category or not memory_key or not memory_value:
        raise ValueError("Category, memory key and value are required")

    with get_connection() as connection:
        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT memory_id
                FROM global_memories
                WHERE category = %s
                  AND memory_key = %s
                ORDER BY updated_at DESC
                LIMIT 1;
                """,
                (category, memory_key)
            )

            existing_memory = cursor.fetchone()

            if existing_memory:

                cursor.execute(
                    """
                    UPDATE global_memories
                    SET memory_value = %s,
                        source_conversation_id = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE memory_id = %s
                    RETURNING memory_id, category, memory_key,
                              memory_value, source_conversation_id,
                              created_at, updated_at;
                    """,
                    (
                        memory_value,
                        source_conversation_id,
                        existing_memory[0]
                    )
                )

            else:

                cursor.execute(
                    """
                    INSERT INTO global_memories (
                        category,
                        memory_key,
                        memory_value,
                        source_conversation_id
                    )
                    VALUES (%s, %s, %s, %s)
                    RETURNING memory_id, category, memory_key,
                              memory_value, source_conversation_id,
                              created_at, updated_at;
                    """,
                    (
                        category,
                        memory_key,
                        memory_value,
                        source_conversation_id
                    )
                )

            row = cursor.fetchone()

    return {
        "memory_id": row[0],
        "category": row[1],
        "memory_key": row[2],
        "memory_value": row[3],
        "source_conversation_id": row[4],
        "created_at": row[5],
        "updated_at": row[6]
    }

def get_global_memories(limit=100):
    """
    Retrieve the latest shared memories across all conversations.
    """

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT memory_id, category, memory_key,
                       memory_value, source_conversation_id,
                       created_at, updated_at
                FROM global_memories
                ORDER BY updated_at DESC
                LIMIT %s;
                """,
                (limit,)
            )

            rows = cursor.fetchall()

    return [
        {
            "memory_id": row[0],
            "category": row[1],
            "memory_key": row[2],
            "memory_value": row[3],
            "source_conversation_id": row[4],
            "created_at": row[5],
            "updated_at": row[6]
        }
        for row in rows
    ]

def search_global_memories(query, limit=10):
    """
    Search shared memories using keyword matching.
    """

    if not query or not query.strip():
        return []

    search_term = f"%{query.strip()}%"

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT memory_id, category, memory_key,
                       memory_value, source_conversation_id,
                       created_at, updated_at
                FROM global_memories
                WHERE memory_key ILIKE %s
                   OR memory_value ILIKE %s
                   OR category ILIKE %s
                ORDER BY updated_at DESC
                LIMIT %s;
                """,
                (
                    search_term,
                    search_term,
                    search_term,
                    limit
                )
            )

            rows = cursor.fetchall()

    return [
        {
            "memory_id": row[0],
            "category": row[1],
            "memory_key": row[2],
            "memory_value": row[3],
            "source_conversation_id": row[4],
            "created_at": row[5],
            "updated_at": row[6]
        }
        for row in rows
    ]