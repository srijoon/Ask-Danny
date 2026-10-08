# Conversation persistence on the "conversations" collection: create/list/get/
# append/delete — every query is scoped by user_id so threads are private — plus
# recent_history(), which trims the history that goes into the prompts.
from datetime import datetime, timezone

from ..auth.users import to_object_id
from ..db import CONVERSATIONS

# failed answers stay visible in the thread but are excluded from chat history —
# feeding an error message back to the model just wastes tokens
_FAILED = {"rate_limited", "error"}


def create(db, user_id, title):
    """Insert a conversation owned by user_id; the title is the first question."""
    now = datetime.now(timezone.utc)
    # the sidebar title is just the first question, trimmed
    conversation = {"user_id": user_id, "title": title[:80], "messages": [],
                    "created_at": now, "updated_at": now}
    conversation["_id"] = db[CONVERSATIONS].insert_one(conversation).inserted_id
    return conversation


def get_for_user(db, conversation_id, user_id):
    """Fetch a conversation only if it belongs to user_id — the filter is the auth."""
    # user_id is part of the query, so the filter itself is the authorization —
    # one user can never read another's thread
    oid = to_object_id(conversation_id)
    return db[CONVERSATIONS].find_one({"_id": oid, "user_id": user_id}) if oid else None


def list_for_user(db, user_id, limit=30):
    """Sidebar list for the chat page: titles + timestamps, newest first."""
    # sidebar list: titles + timestamps only, message bodies load on demand
    return list(
        db[CONVERSATIONS]
        .find({"user_id": user_id}, {"title": 1, "updated_at": 1})
        .sort("updated_at", -1)
        .limit(limit)
    )


def append_exchange(db, conversation_id, question, answer):
    """Store a question and its answer together on the conversation."""
    # both halves of the exchange go in one $push so a crash can't leave a
    # question in the thread without its answer
    now = datetime.now(timezone.utc)
    db[CONVERSATIONS].update_one(
        {"_id": conversation_id},
        {
            "$push": {
                "messages": {
                    "$each": [
                        {"role": "user", "content": question, "created_at": now},
                        {
                            "role": "assistant",
                            "content": answer.text,
                            "status": answer.status,
                            "sources": answer.sources,
                            "search_query": answer.search_query,
                            "created_at": now,
                        },
                    ]
                }
            },
            "$set": {"updated_at": now},
        },
    )


def recent_history(conversation, turns):
    """The last `turns` successful exchanges, flattened for the prompts."""
    # messages alternate user/assistant; zip them into exchanges and keep only the
    # last `turns` so history can't grow the prompt (and its cost) without bound
    messages = conversation.get("messages", []) if conversation else []
    pairs = []
    for question, answer in zip(messages[::2], messages[1::2]):
        if answer.get("status") not in _FAILED:
            pairs.append(({"role": "user", "content": question["content"]},
                          {"role": "assistant", "content": answer["content"]}))
    return [message for pair in pairs[-turns:] for message in pair] if turns > 0 else []


def delete(db, conversation_id, user_id):
    """Delete a conversation only if it belongs to user_id (same scoping as get)."""
    oid = to_object_id(conversation_id)
    if oid:
        db[CONVERSATIONS].delete_one({"_id": oid, "user_id": user_id})
