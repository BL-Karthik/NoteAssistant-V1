
from threading import Lock
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import uuid


_sessions = {}
_session_lock = Lock()

# Separate locks for individual chat requests.
_chat_request_locks = {}
_chat_request_locks_guard = Lock()


@contextmanager
def chat_request_lock(conversation_id, client_message_id):
    """
    Serialize requests using the same conversation and message ID.
    Different messages can process concurrently.
    """

    key = (conversation_id, client_message_id)

    with _chat_request_locks_guard:
        entry = _chat_request_locks.get(key)

        if entry is None:
            entry = {
                "lock": Lock(),
                "users": 0
            }
            _chat_request_locks[key] = entry

        entry["users"] += 1

    entry["lock"].acquire()

    try:
        yield
    finally:
        entry["lock"].release()

        with _chat_request_locks_guard:
            entry["users"] -= 1

            if entry["users"] == 0:
                _chat_request_locks.pop(key, None)


def _current_time():
    return datetime.now(timezone.utc)


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    metadata=None,
    client_message_id=None,
    saved=False
):
    if not conversation_id or not isinstance(conversation_id, str):
        raise ValueError("Valid conversation_id is required")

    if not isinstance(content, str) or not content.strip():
        return None

    if role not in ("user", "assistant", "system"):
        raise ValueError("Invalid message role")

    if metadata is None:
        metadata = {}

    if not isinstance(metadata, dict):
        raise ValueError("Message metadata must be a dictionary")

    client_message_id = client_message_id or str(uuid.uuid4())
    now = _current_time()

    message = {
        "client_message_id": client_message_id,
        "role": role,
        "content": content.strip(),
        "metadata": deepcopy(metadata),
        "created_at": now.isoformat(),
        "_saved": saved
    }

    with _session_lock:

        if conversation_id not in _sessions:
            _sessions[conversation_id] = {
                "messages": [],
                "last_activity": now
            }

        session = _sessions[conversation_id]

        existing_message = next(
            (
                item for item in session["messages"]
                if item["client_message_id"] == client_message_id
            ),
            None
        )

        if existing_message:
            session["last_activity"] = now
            return deepcopy(existing_message)

        session["messages"].append(message)
        session["last_activity"] = now

        return deepcopy(message)


def get_messages(conversation_id: str):
    with _session_lock:

        session = _sessions.get(conversation_id)

        if not session:
            return []

        return [
            {
                key: deepcopy(value)
                for key, value in message.items()
                if key != "_saved"
            }
            for message in session["messages"]
        ]


def get_pending_messages(conversation_id: str):
    with _session_lock:

        session = _sessions.get(conversation_id)

        if not session:
            return []

        return [
            {
                key: deepcopy(value)
                for key, value in message.items()
                if key != "_saved"
            }
            for message in session["messages"]
            if not message["_saved"]
        ]


def get_inactive_sessions(inactivity_seconds=300):
    now = _current_time()
    inactive_sessions = []

    with _session_lock:

        for conversation_id, session in _sessions.items():

            inactive_duration = (
                now - session["last_activity"]
            ).total_seconds()

            if inactive_duration < inactivity_seconds:
                continue

            pending_messages = [
                {
                    key: deepcopy(value)
                    for key, value in message.items()
                    if key != "_saved"
                }
                for message in session["messages"]
                if not message["_saved"]
            ]

            if pending_messages:
                inactive_sessions.append({
                    "conversation_id": conversation_id,
                    "messages": pending_messages
                })

    return inactive_sessions


def mark_messages_saved(conversation_id: str, client_message_ids):
    if not client_message_ids:
        return 0

    accepted_ids = set(client_message_ids)
    marked_count = 0

    with _session_lock:

        session = _sessions.get(conversation_id)

        if not session:
            return 0

        for message in session["messages"]:

            if (
                message["client_message_id"] in accepted_ids
                and not message["_saved"]
            ):
                message["_saved"] = True
                marked_count += 1

    return marked_count


def get_session_activity(conversation_id: str):
    with _session_lock:

        session = _sessions.get(conversation_id)

        if not session:
            return None

        return session["last_activity"].isoformat()


def clear_session(conversation_id: str):
    with _session_lock:
        _sessions.pop(conversation_id, None)


def get_session_count():
    with _session_lock:
        return len(_sessions)


def clear_all_sessions():
    with _session_lock:
        _sessions.clear()
