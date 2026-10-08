from datetime import datetime, timezone

from ..auth.users import to_object_id
from ..db import CONVERSATIONS

_FAILED = {"rate_limited", "error"}


def create(db, user_id, title):
    now = datetime.now(timezone.utc)
    conversation = {"user_id": user_id, "title": title[:80], "messages": [],
                    "created_at": now, "updated_at": now}
    conversation["_id"] = db[CONVERSATIONS].insert_one(conversation).inserted_id
    return conversation


def get_for_user(db, conversation_id, user_id):
    oid = to_object_id(conversation_id)
    return db[CONVERSATIONS].find_one({"_id": oid, "user_id": user_id}) if oid else None


def list_for_user(db, user_id, limit=30):
    return list(
        db[CONVERSATIONS]
        .find({"user_id": user_id}, {"title": 1, "updated_at": 1})
        .sort("updated_at", -1)
        .limit(limit)
    )


def append_exchange(db, conversation_id, question, answer):
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
    messages = conversation.get("messages", []) if conversation else []
    pairs = []
    for question, answer in zip(messages[::2], messages[1::2]):
        if answer.get("status") not in _FAILED:
            pairs.append(({"role": "user", "content": question["content"]},
                          {"role": "assistant", "content": answer["content"]}))
    return [message for pair in pairs[-turns:] for message in pair] if turns > 0 else []


def delete(db, conversation_id, user_id):
    oid = to_object_id(conversation_id)
    if oid:
        db[CONVERSATIONS].delete_one({"_id": oid, "user_id": user_id})
