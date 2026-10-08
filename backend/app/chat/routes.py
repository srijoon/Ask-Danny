# The chat UI and its JSON endpoint: GET / renders the page, POST /chat/ask runs
# the RAG pipeline in chat/answer.py and persists exchanges via
# chat/conversations.py. Conversation history is always scoped to g.user.
import logging

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, url_for
from pymongo.errors import PyMongoError

from ..auth.routes import login_required
from ..db import get_db
from ..permissions import principals_for
from . import conversations
from .answer import answer_question

log = logging.getLogger(__name__)

bp = Blueprint("chat", __name__)

# bounds what we forward to the LLM; also a sanity cap on junk input
MAX_QUESTION_CHARS = 2000


@bp.get("/")
@login_required
def index():
    """Render the chat page; ?c=<id> reopens a conversation the user owns."""
    db = get_db()
    active = None
    if request.args.get("c"):
        # get_for_user scopes by user_id, so poking someone else's id just 404s
        active = conversations.get_for_user(db, request.args["c"], g.user["_id"])
        if active is None:
            abort(404)
    # the template gets only the fields it renders, never the raw document
    messages = [
        {key: m.get(key) for key in ("role", "content", "status", "sources", "search_query")}
        for m in (active or {}).get("messages", [])
    ]
    return render_template(
        "chat.html",
        conversations=conversations.list_for_user(db, g.user["_id"]),
        active=active,
        messages=messages,
    )


@bp.post("/chat/ask")
@login_required
def ask():
    """The web UI's question endpoint — the Next.js frontend uses /api/ask instead."""
    # silent=True so malformed JSON becomes {} and hits the "empty question" path
    data = request.get_json(silent=True) or {}
    question = str(data.get("question") or "").strip()
    if not question:
        return jsonify(error="Please type a question."), 400
    if len(question) > MAX_QUESTION_CHARS:
        return jsonify(error=f"Questions are limited to {MAX_QUESTION_CHARS} characters."), 400

    db = get_db()
    conversation = None
    if data.get("conversation_id"):
        conversation = conversations.get_for_user(db, data["conversation_id"], g.user["_id"])
        if conversation is None:
            return jsonify(error="That conversation no longer exists."), 404

    history = conversations.recent_history(conversation, current_app.config["CHAT_HISTORY_TURNS"])
    try:
        answer = answer_question(question, history, principals_for(g.user))
        # the conversation row is created only after an answer exists, so a failed
        # first question doesn't leave an empty thread in the sidebar
        if conversation is None:
            conversation = conversations.create(db, g.user["_id"], question)
        conversations.append_exchange(db, conversation["_id"], question, answer)
    except PyMongoError:
        log.exception("Database error while answering")
        return jsonify(error="The document database is unreachable right now. Please try again."), 503

    return jsonify(
        conversation_id=str(conversation["_id"]),
        title=conversation["title"],
        answer={
            "content": answer.text,
            "status": answer.status,
            "sources": answer.sources,
            "search_query": answer.search_query,
        },
    )


@bp.post("/chat/<conversation_id>/delete")
@login_required
def delete(conversation_id):
    """Remove one of the user's own conversations."""
    # scoped by user_id like get_for_user: the filter itself is the authorization
    conversations.delete(get_db(), conversation_id, g.user["_id"])
    return redirect(url_for("chat.index"))
