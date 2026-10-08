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

MAX_QUESTION_CHARS = 2000


@bp.get("/")
@login_required
def index():
    db = get_db()
    active = None
    if request.args.get("c"):
        active = conversations.get_for_user(db, request.args["c"], g.user["_id"])
        if active is None:
            abort(404)
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
    conversations.delete(get_db(), conversation_id, g.user["_id"])
    return redirect(url_for("chat.index"))
