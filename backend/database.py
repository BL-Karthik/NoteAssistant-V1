
import os

import psycopg
from dotenv import load_dotenv


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


# -----------------------------------
# DATABASE CONNECTION
# -----------------------------------

def get_connection():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Configure it in your backend .env file."
        )

    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


# -----------------------------------
# TEST DATABASE CONNECTION
# -----------------------------------

def test_database_connection():

    try:

        with get_connection() as connection:

            with connection.cursor() as cursor:

                cursor.execute("SELECT 1")

                result = cursor.fetchone()

                print("Database connection successful:", result)

                return True

    except Exception as error:

        print("Database connection failed:", error)

        return False


# -----------------------------------
# CREATE TABLES
# -----------------------------------

def create_tables():

    with get_connection() as connection:

        with connection.cursor() as cursor:

            # -----------------------------------
            # CONVERSATIONS TABLE
            # -----------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT 'New Conversation',
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # -----------------------------------
            # MESSAGES TABLE
            # -----------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id BIGSERIAL PRIMARY KEY,

                    conversation_id TEXT NOT NULL
                        REFERENCES conversations(conversation_id)
                        ON DELETE CASCADE,

                    client_message_id TEXT,

                    role TEXT NOT NULL
                        CHECK (role IN ('user', 'assistant', 'system')),

                    content TEXT NOT NULL,

                    metadata JSONB DEFAULT '{}'::jsonb,

                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # -----------------------------------
            # SAFE MIGRATION FOR EXISTING TABLES
            # -----------------------------------

            cursor.execute(
                """
                ALTER TABLE messages
                ADD COLUMN IF NOT EXISTS metadata JSONB
                DEFAULT '{}'::jsonb;
                """
            )

            cursor.execute(
                """
                ALTER TABLE messages
                ADD COLUMN IF NOT EXISTS client_message_id TEXT;
                """
            )

            # -----------------------------------
            # MESSAGE INDEX
            # -----------------------------------

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages(conversation_id);
                """
            )

            # -----------------------------------
            # IDEMPOTENCY INDEX
            # -----------------------------------

            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_messages_client_id
                ON messages (
                    conversation_id,
                    client_message_id
                )
                WHERE client_message_id IS NOT NULL;
                """
            )

            # -----------------------------------
            # GLOBAL MEMORIES TABLE
            # -----------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS global_memories (

                    memory_id BIGSERIAL PRIMARY KEY,

                    category TEXT NOT NULL,

                    memory_key TEXT NOT NULL UNIQUE,

                    memory_value TEXT NOT NULL,

                    source_conversation_id TEXT
                        REFERENCES conversations(conversation_id)
                        ON DELETE SET NULL,

                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # -----------------------------------
            # GLOBAL MEMORY INDEXES
            # -----------------------------------

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_global_memories_category
                ON global_memories(category);
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_global_memories_updated
                ON global_memories(updated_at DESC);
                """
            )

    print("Database tables and indexes initialized successfully.")
