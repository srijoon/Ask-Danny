# The JSON API mounted at /api: session helpers (csrf/login/logout/me), the
# /api/files CRUD endpoints over shared and group pools, and read-only admin
# endpoints. It reuses the web app's auth decorators, permissions and ingestion
# service rather than duplicating them.
import hashlib
import logging
import os
from collections import Counter
from datetime import timezone

from flask import Blueprint, current_app, g, jsonify, request, session
from pymongo.errors import PyMongoError
from werkzeug.exceptions import HTTPException

from .auth.routes import admin_required, login_required
from .auth.users import authenticate, known_groups, list_users, to_object_id
from .chat import conversations
from .chat.answer import answer_question
from .chat.routes import MAX_QUESTION_CHARS
from .db import CHUNKS, CONVERSATIONS, DOCUMENTS, USERS, get_db
from .generation.llm import get_llm
from .ingestion.parsers import supported_extensions
from .ingestion.service import IngestionError, clean_filename, delete_document, ingest_document
from .permissions import EVERYONE, GROUP_RE, access_groups, document_access, principals_for
from .security import csrf_token

log = logging.getLogger(__name__)

# JSON API for the spec's /files and admin screens. It sits on top of the session login, CSRF
# hook, access principals and ingestion service the web UI already uses, so both share one
# user store and one permission model.
api = Blueprint("api", __name__)

# a pool is either "shared" (stored as the "everyone" principal) or "group:<name>"
SHARED_POOL = "shared"
# the title is prepended to every chunk before embedding, so it has to stay short
MAX_TITLE_CHARS = 200
# short, client-friendly wording instead of werkzeug's long default descriptions
_ERROR_MESSAGES = {403: "Admin access required", 404: "Not found", 405: "Method not allowed"}


def _iso(moment):
    """Serialize a mongo datetime as ISO-8601 with an explicit UTC offset."""
    # mongo hands back naive datetimes that are UTC; I always emit an explicit offset so
    # clients never have to guess the timezone
    return moment.replace(tzinfo=moment.tzinfo or timezone.utc).isoformat(timespec="milliseconds")


def _pool_principal(pool_id):
    """Translate a public poolId into the access principal stored on documents/chunks."""
    # translate a public poolId into the access principal stored on documents and chunks;
    # None means the id is malformed (group names must match the same rule users get)
    if pool_id == SHARED_POOL:
        return EVERYONE
    if pool_id.startswith("group:") and GROUP_RE.fullmatch(pool_id.removeprefix("group:")):
        return pool_id
    return None


def _resolve_pool(pool_id):
    """Validate a poolId and the caller's membership in it — (principal, None) or (None, error)."""
    # returns (principal, None) when the caller may use the pool, or (None, error response).
    # members only reach pools they hold; admins may target any valid pool, like the
    # Documents page lets them pick any group
    principal = _pool_principal(pool_id or "")
    if principal is None:
        return None, (jsonify(error="poolId must be 'shared' or 'group:<name>'."), 400)
    if not g.user.get("is_admin") and principal not in principals_for(g.user):
        return None, (jsonify(error="You don't have access to this pool."), 403)
    return principal, None


def _can_read(doc):
    """Whether g.user may read a document — same principal-intersection rule as retrieval."""
    # same rule as retrieval: a member sees a document when its access list shares at least
    # one principal with theirs; admins see everything, matching the Documents page
    return g.user.get("is_admin") or bool(set(doc["access"]) & set(principals_for(g.user)))


def _readable_doc(doc_id):
    """Load a document by id if the current user may read it, else None (like 404)."""
    # load a document by id for the current user, or None
    oid = to_object_id(doc_id)
    doc = get_db()[DOCUMENTS].find_one({"_id": oid}) if oid else None
    # unreadable looks the same as missing, so ids can't be probed
    return doc if doc and _can_read(doc) else None


def _me(user):
    """The API's public view of a user (never the password hash) + their pool list."""
    # public view of a user: never includes the password hash. pools are what the upload and
    # list endpoints accept as poolId for this user
    groups = user.get("groups", [])
    pools = [{"id": SHARED_POOL, "type": "shared", "name": "Shared"}]
    pools += [{"id": f"group:{group}", "type": "group", "name": group} for group in groups]
    return {"id": str(user["_id"]), "username": user["username"], "groups": groups,
            "isAdmin": bool(user.get("is_admin")), "pools": pools}


def _file(doc):
    """The API's public view of a document, with principals translated back to poolIds."""
    # public view of a document. poolIds hide the internal principals: "everyone" becomes
    # "shared", and the uploader's own "user:<name>" entry is left out because it isn't a pool
    pool_ids = [SHARED_POOL if p == EVERYONE else p for p in doc["access"]
                if p == EVERYONE or p.startswith("group:")]
    return {"id": str(doc["_id"]), "title": doc["title"], "filename": doc["filename"],
            "fileType": doc["file_type"], "size": doc["size_bytes"], "poolIds": pool_ids,
            "uploadedBy": doc["uploaded_by"], "createdAt": _iso(doc["created_at"]),
            "chunkCount": doc["chunk_count"]}


@api.errorhandler(HTTPException)
def http_error(exc):
    """Turn aborts/CSRF/size errors inside /api into {"error": ...} JSON."""
    # every HTTP error raised inside /api (abort, CSRF failure, oversized body) becomes
    # {"error": ...} so a frontend never has to parse an HTML page
    if exc.code == 413:
        limit = current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return jsonify(error=f"File too large (max {limit} MB)"), 413
    return jsonify(error=_ERROR_MESSAGES.get(exc.code, exc.description)), exc.code


@api.errorhandler(PyMongoError)
def database_error(exc):
    """Atlas outage -> 503 so the client knows to retry rather than report a bug."""
    # Atlas being unreachable is a temporary outage, not a bug: 503 tells the client to retry
    log.error("Database error: %s", exc)
    return jsonify(error="Database unavailable"), 503


@api.errorhandler(Exception)
def unexpected_error(exc):
    """Last-resort handler: log the traceback, return a generic 500 — no internals leak."""
    # last resort: log the traceback for me, return a generic message so internals never leak
    log.exception("Unhandled API error")
    return jsonify(error="Internal server error"), 500


@api.app_errorhandler(404)
@api.app_errorhandler(405)
def routing_error(exc):
    """JSON 404/405 under /api only — the Jinja pages keep their HTML error pages."""
    # unknown URLs and wrong methods never reach a blueprint, so this is registered app-wide.
    # only /api answers JSON; the Jinja pages keep the default HTML errors
    if request.path.startswith("/api/"):
        return jsonify(error=_ERROR_MESSAGES[exc.code]), exc.code
    return exc


@api.get("/health")
def health():
    """Liveness check for the dev proxy and deploys — touches no database."""
    # liveness check for the dev proxy and deploys; touches no database
    return jsonify(status="ok")


@api.get("/hello")
def hello():
    """Scaffold's connectivity demo endpoint — kept so its test and demo keep working."""
    # starter endpoint from the original scaffold, kept so its test and the frontend demo work
    name = request.args.get("name", "world")
    return jsonify(message=f"Hello, {name}!")


@api.get("/csrf")
def csrf():
    """First call for any client: returns the token to echo on later mutations."""
    # the CSRF hook guards every POST/DELETE, including /api/login, so a client fetches a
    # token here first and sends it back as X-CSRF-Token
    return jsonify(csrfToken=csrf_token())


@api.post("/login")
def login():
    """JSON sign-in — same session cookie as the web form, so both UIs share auth."""
    # JSON version of the web login form; sets the same session cookie, so a user signed in
    # here is signed in to the web UI too
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}
    username, password = data.get("username"), data.get("password")
    # authenticate() calls .strip(), so anything that isn't a string would crash it
    if not isinstance(username, str) or not isinstance(password, str):
        return jsonify(error="username and password are required."), 400
    user = authenticate(get_db(), username, password)
    if user is None:
        return jsonify(error="Wrong username or password."), 401
    # fresh session on login so a pre-login session id can't be reused (session fixation)
    session.clear()
    session["user_id"] = str(user["_id"])
    # clear() dropped the old token, so hand out the new one
    return jsonify(user=_me(user), csrfToken=csrf_token())


@api.post("/logout")
def logout():
    """Clear the session; safe to call when already signed out."""
    # safe to call when already signed out
    session.clear()
    return "", 204


@api.get("/me")
@login_required
def me():
    """Who the caller is and which pools they may use — the frontend's pool picker."""
    # who am I and which pools can I use; the frontend builds its pool picker from this
    return jsonify(_me(g.user))


@api.post("/ask")
@login_required
def ask():
    """Question endpoint: same RAG pipeline + conversations as the web chat."""
    # the spec's question endpoint: same pipeline as the web chat (rewrite → filtered
    # retrieval → LLM only when something relevant is found), and answers persist to the
    # same conversations, so a question asked here shows up in the web chat too
    data = request.get_json(silent=True) or {}
    question = str(data.get("question") or "").strip()
    if not question:
        return jsonify(error="Please type a question."), 400
    if len(question) > MAX_QUESTION_CHARS:
        return jsonify(error=f"Questions are limited to {MAX_QUESTION_CHARS} characters."), 400

    db = get_db()
    conversation = None
    conversation_id = data.get("conversationId")
    if conversation_id:
        # scoped by user_id, so pointing at someone else's thread answers 404
        conversation = conversations.get_for_user(db, conversation_id, g.user["_id"])
        if conversation is None:
            return jsonify(error="Conversation not found"), 404

    history = conversations.recent_history(conversation, current_app.config["CHAT_HISTORY_TURNS"])
    try:
        answer = answer_question(question, history, principals_for(g.user))
        # create the thread only once an answer exists, so a failed first question
        # doesn't leave an empty conversation behind
        if conversation is None:
            conversation = conversations.create(db, g.user["_id"], question)
        conversations.append_exchange(db, conversation["_id"], question, answer)
    except PyMongoError:
        log.exception("Database error while answering")
        return jsonify(error="The document database is unreachable right now. Please try again."), 503

    return jsonify(
        conversationId=str(conversation["_id"]),
        title=conversation["title"],
        answer={
            "content": answer.text,
            "status": answer.status,
            "sources": answer.sources,
            "searchQuery": answer.search_query,
        },
    )


@api.get("/files")
@login_required
def list_files():
    """List documents the caller can see (admins: all), newest first; ?poolId narrows."""
    # everything the caller can see, newest first; admins see all documents
    query = {} if g.user.get("is_admin") else {"access": {"$in": principals_for(g.user)}}
    if "poolId" in request.args:
        # narrowing to one pool still goes through the membership check
        principal, error = _resolve_pool(request.args["poolId"])
        if error:
            return error
        query = {"access": principal}
    docs = get_db()[DOCUMENTS].find(query).sort("created_at", -1)
    return jsonify(files=[_file(doc) for doc in docs])


@api.get("/files/<doc_id>")
@login_required
def get_file(doc_id):
    """Metadata for one document; inaccessible ones answer 404 like missing ones."""
    # metadata for one document; invisible documents answer 404 like missing ones
    doc = _readable_doc(doc_id)
    if doc is None:
        return jsonify(error="File not found"), 404
    return jsonify(file=_file(doc))


@api.post("/files")
@login_required
def upload_file():
    """Multipart upload into a pool: validate, dedup, then ingest_document() does the rest."""
    # upload = validate, refuse duplicates, then hand off to the shared ingestion service
    # (parse, chunk, embed locally, store in Atlas). cheap checks run first so a bad request
    # never costs an embedding pass
    upload = request.files.get("file")
    filename = clean_filename(upload.filename) if upload else ""
    if not filename:
        return jsonify(error="Choose a file to upload."), 400
    principal, error = _resolve_pool(request.form.get("poolId"))
    if error:
        return error
    title = request.form.get("title", "").strip()
    if len(title) > MAX_TITLE_CHARS:
        return jsonify(error=f"Titles are limited to {MAX_TITLE_CHARS} characters."), 400
    ext = os.path.splitext(filename)[1].lower()
    if ext not in supported_extensions():
        return jsonify(error=f"Unsupported file type '{ext or filename}'. "
                             f"Supported: {', '.join(supported_extensions())}."), 415

    data = upload.read()
    # ingest_document checks duplicates too, but its message names the existing title,
    # which a member may not be allowed to see
    existing = get_db()[DOCUMENTS].find_one({"sha256": hashlib.sha256(data).hexdigest()},
                                            {"access": 1})
    if existing:
        # only point at the existing copy when the uploader could open it anyway
        return jsonify(error="An identical file has already been uploaded.",
                       fileId=str(existing["_id"]) if _can_read(existing) else None), 409

    # shared → ["everyone"]; group → ["group:<name>", "user:<me>"] so I keep access to my own
    # upload even if I later leave the group
    access = document_access([principal.removeprefix("group:")], everyone=principal == EVERYONE,
                             owner=g.user["username"])
    try:
        doc = ingest_document(filename, data, access=access, uploaded_by=g.user["username"],
                              title=title or None)
    except IngestionError as exc:
        # the service wraps every failure in IngestionError; a database cause is an outage
        # (503), anything else is a problem with the file itself (422)
        if isinstance(exc.__cause__, PyMongoError):
            log.error("Couldn't save %s: %s", filename, exc.__cause__)
            return jsonify(error="Database unavailable"), 503
        return jsonify(error=str(exc)), 422
    return jsonify(file=_file(doc)), 201


@api.delete("/files/<doc_id>")
@login_required
def delete_file(doc_id):
    """Remove a document and its chunks; spec says anyone who can see it may delete it."""
    # per the spec, anyone who can see a document can remove it from the pool; the service
    # deletes its chunks first so search never returns orphans
    doc = _readable_doc(doc_id)
    if doc is None:
        return jsonify(error="File not found"), 404
    delete_document(doc["_id"])
    return "", 204


@api.get("/admin/users")
@admin_required
def admin_users():
    """Read-only user list for an admin screen — password hashes never included."""
    # read-only user list for an admin screen; list_users already drops password hashes
    return jsonify(users=[
        {"id": str(user["_id"]), "username": user["username"], "groups": user.get("groups", []),
         "isAdmin": bool(user.get("is_admin")), "createdAt": _iso(user["created_at"])}
        for user in list_users(get_db())
    ])


@api.get("/admin/groups")
@admin_required
def admin_groups():
    """Every known group with its members and document count, for an admin screen."""
    # groups are implicit (they exist on users and documents, not in their own collection),
    # so I take the same union the Documents page builds and count members and documents
    db = get_db()
    users = list_users(db)
    documents = Counter(group for doc in db[DOCUMENTS].find({}, {"access": 1})
                        for group in access_groups(doc["access"]))
    names = sorted(set(known_groups(db)) | set(documents))
    return jsonify(groups=[
        {"id": f"group:{name}", "name": name,
         "members": [user["username"] for user in users if name in user.get("groups", [])],
         "documentCount": documents[name]}
        for name in names
    ])


@api.get("/admin/usage")
@admin_required
def admin_usage():
    """Volume stats for the admin screen: storage vs the M0 limit and question outcomes."""
    # the stack costs $0 (local embeddings, free LLM), so "usage" here means volume: how much
    # is stored against the M0 limit and how questions turned out. every assistant message in
    # a conversation is one answered question
    db = get_db()
    # the four statuses the answer flow produces are always present, even at 0
    by_status = dict.fromkeys(("ok", "no_results", "rate_limited", "error"), 0)
    by_user_id = Counter()
    # only standard stages so this runs the same on Atlas and on mongomock in tests
    rows = db[CONVERSATIONS].aggregate([
        {"$unwind": "$messages"},
        {"$match": {"messages.role": "assistant"}},
        {"$group": {"_id": {"user": "$user_id", "status": "$messages.status"}, "n": {"$sum": 1}}},
    ])
    for row in rows:
        status = row["_id"].get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + row["n"]
        by_user_id[row["_id"]["user"]] += row["n"]
    # conversations store user ids; deleted users fall back to their raw id below
    names = {user["_id"]: user["username"]
             for user in db[USERS].find({"_id": {"$in": list(by_user_id)}}, {"username": 1})}
    size = next(iter(db[DOCUMENTS].aggregate(
        [{"$group": {"_id": None, "bytes": {"$sum": "$size_bytes"}}}])), None)
    return jsonify(
        documents={"count": db[DOCUMENTS].count_documents({}),
                   "chunks": db[CHUNKS].count_documents({}),
                   "totalBytes": size["bytes"] if size else 0},
        questions={"total": sum(by_status.values()), "byStatus": by_status,
                   "byUser": {names.get(uid, str(uid)): n for uid, n in by_user_id.items()}},
        # a no_results answer never reaches the LLM
        savings={"answerCallsSkipped": by_status["no_results"]},
        llm=get_llm().describe(),
    )
