# Admin-only HTML pages: /admin/documents (upload, change access, delete, plus
# search-index status) and /admin/users (create/edit/delete). Reuses the
# ingestion service and auth helpers; every view sits behind admin_required.
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from ..auth.routes import admin_required
from ..auth.users import (UserError, create_user, delete_user, known_groups, list_users,
                          to_object_id, update_user)
from ..db import DOCUMENTS, get_db, search_index_status
from ..ingestion.parsers import supported_extensions
from ..ingestion.service import (IngestionError, clean_filename, delete_document, ingest_document, set_document_access)
from ..generation.llm import get_llm
from ..permissions import EVERYONE, access_groups, describe_access, document_access

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _form_access(owner=None):
    """Build a document access list from the form's group checkboxes + free-text field."""
    # checkboxes give one value per existing group; "new_groups" is a free-text
    # field for groups that don't exist yet — parse_groups handles both shapes
    groups = request.form.getlist("groups") + [request.form.get("new_groups", "")]
    return document_access(groups, everyone=bool(request.form.get("everyone")), owner=owner)


def _search_status():
    """Report index status + effective search mode for the documents page."""
    # shown on the documents page so an admin can tell at a glance whether hybrid
    # search is live or a text index is still building/missing
    cfg = current_app.config
    indexes = search_index_status(get_db(), cfg)
    vector = indexes.get(cfg["VECTOR_INDEX_NAME"], "MISSING")
    text = indexes.get(cfg["TEXT_INDEX_NAME"], "MISSING")
    hybrid = cfg["KEYWORD_SEARCH_ENABLED"] and text == "READY"
    return {"vector": vector, "text": text if cfg["KEYWORD_SEARCH_ENABLED"] else "DISABLED",
            "mode": "Hybrid (vector + keyword)" if hybrid else "Vector only"}


@bp.get("/documents")
@admin_required
def documents():
    """List every document with its access label, plus groups and index status."""
    docs = list(get_db()[DOCUMENTS].find().sort("created_at", -1))
    for doc in docs:
        doc["access_label"] = describe_access(doc["access"])
        doc["access_groups"] = access_groups(doc["access"])
    # a group can live on a document even after no user belongs to it, so the
    # checkbox list merges "groups users have" with "groups documents reference"
    db_groups = set(known_groups(get_db()))
    doc_groups = {group for doc in docs for group in doc["access_groups"]}
    return render_template(
        "admin/documents.html",
        documents=docs,
        groups=sorted(db_groups | doc_groups),
        extensions=supported_extensions(),
        status=_search_status(),
        llm=get_llm().describe(),
        rewrite=current_app.config["QUERY_REWRITE_ENABLED"],
    )


@bp.post("/documents")
@admin_required
def upload():
    """Ingest one or more files into the chosen groups via ingest_document()."""
    # browsers send empty file inputs alongside the real ones
    files = [f for f in request.files.getlist("files") if f and f.filename]
    if not files:
        flash("Choose at least one file to upload.", "error")
        return redirect(url_for(".documents"))
    try:
        access = _form_access(owner=g.user["username"])
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for(".documents"))

    # a custom title only makes sense when exactly one file is being uploaded
    title = request.form.get("title", "").strip() if len(files) == 1 else None
    for file in files:
        # clean_filename keeps non-ASCII names that secure_filename would strip to nothing
        filename = clean_filename(file.filename) or "upload"
        try:
            doc = ingest_document(filename, file.read(), access=access,
                                  uploaded_by=g.user["username"], title=title)
            flash(f"Added '{doc['title']}' ({doc['chunk_count']} chunks).", "success")
        except IngestionError as exc:
            flash(str(exc), "error")
    return redirect(url_for(".documents"))


@bp.post("/documents/<doc_id>/access")
@admin_required
def change_access(doc_id):
    """Rewrite a document's access list; keeps the uploader's own access."""
    oid = to_object_id(doc_id) or abort(404)
    doc = get_db()[DOCUMENTS].find_one({"_id": oid}, {"access": 1}) or abort(404)
    try:
        access = _form_access()
        # keep the uploader's user: principal when narrowing to groups, so the
        # person who added the file doesn't silently lose access to it
        if access and EVERYONE not in access:
            access += [p for p in doc["access"] if p.startswith("user:")]
        set_document_access(oid, access)
        flash("Access updated. Search indexes pick up the change within a few seconds.", "success")
    except (ValueError, IngestionError) as exc:
        flash(str(exc), "error")
    return redirect(url_for(".documents"))


@bp.post("/documents/<doc_id>/delete")
@admin_required
def remove_document(doc_id):
    """Delete a document and all its chunks via delete_document()."""
    delete_document(to_object_id(doc_id) or abort(404))
    flash("Document deleted.", "success")
    return redirect(url_for(".documents"))


@bp.get("/users")
@admin_required
def users():
    """List all users and the known groups for the user-management page."""
    return render_template("admin/users.html", users=list_users(get_db()),
                           groups=known_groups(get_db()))


@bp.post("/users")
@admin_required
def add_user():
    """Create a user from the form (username, password, groups, admin flag)."""
    try:
        user = create_user(get_db(), request.form.get("username"), request.form.get("password"),
                           groups=request.form.get("groups", ""),
                           is_admin=bool(request.form.get("is_admin")))
        flash(f"Created user '{user['username']}'.", "success")
    except UserError as exc:
        flash(str(exc), "error")
    return redirect(url_for(".users"))


@bp.post("/users/<user_id>")
@admin_required
def edit_user(user_id):
    """Update a user's groups/admin flag/password; blocks self-demotion."""
    oid = to_object_id(user_id) or abort(404)
    is_admin = bool(request.form.get("is_admin"))
    # the obvious foot-gun: demoting yourself locks the whole admin UI
    if oid == g.user["_id"] and not is_admin:
        flash("You can't remove your own admin rights.", "error")
        return redirect(url_for(".users"))
    try:
        # an empty password field means "leave the password unchanged"
        update_user(get_db(), oid, groups=request.form.get("groups", ""), is_admin=is_admin,
                    password=request.form.get("password") or None)
        flash("User updated.", "success")
    except UserError as exc:
        flash(str(exc), "error")
    return redirect(url_for(".users"))


@bp.post("/users/<user_id>/delete")
@admin_required
def remove_user(user_id):
    """Delete a user — never your own account."""
    oid = to_object_id(user_id) or abort(404)
    if oid == g.user["_id"]:
        flash("You can't delete your own account.", "error")
    else:
        delete_user(get_db(), oid)
        flash("User deleted.", "success")
    return redirect(url_for(".users"))
