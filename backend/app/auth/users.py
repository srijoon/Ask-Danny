# User persistence on the "users" collection: create/authenticate/list/update/
# delete. Passwords are stored as werkzeug hashes and never leave this module.
# Used by auth/routes.py, the admin UI, the /api endpoints and the CLI.
import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import USERS
from ..permissions import parse_groups

# usernames end up inside "user:<name>" access principals, so keep the charset
# strict — a ":" in a name could forge "group:"-style principals
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,49}$")
MIN_PASSWORD_LENGTH = 8


class UserError(ValueError):
    # validation problems the caller can safely flash to the user
    pass


def to_object_id(value):
    """Parse a value into an ObjectId, or None if it isn't one."""
    # ObjectId() raises on malformed input; callers treat None as "not found"
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def _check_password(password):
    """Enforce the minimum password length (shared by create_user and update_user)."""
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise UserError(f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")


def create_user(db, username, password, groups=(), is_admin=False):
    """Insert a user with a hashed password; UserError on bad input or duplicates."""
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise UserError("Usernames are 2-50 lowercase letters, digits, '.', '-' or '_'.")
    _check_password(password)
    try:
        groups = parse_groups(groups)
    except ValueError as exc:
        raise UserError(str(exc)) from exc
    user = {
        "username": username,
        "password_hash": generate_password_hash(password),
        "groups": groups,
        "is_admin": bool(is_admin),
        "created_at": datetime.now(timezone.utc),
    }
    try:
        user["_id"] = db[USERS].insert_one(user).inserted_id
    except DuplicateKeyError as exc:
        raise UserError(f"User '{username}' already exists.") from exc
    return user


def authenticate(db, username, password):
    """Return the user doc on good credentials, else None (login form and /api/login)."""
    # one lookup for both failure cases; returning None either way keeps the login
    # error message from revealing which usernames exist
    user = db[USERS].find_one({"username": (username or "").strip().lower()})
    if user and check_password_hash(user["password_hash"], password or ""):
        return user
    return None


def get_user(db, user_id):
    """Look up a user by id for load_user(); None when missing or malformed."""
    oid = to_object_id(user_id)
    return db[USERS].find_one({"_id": oid}) if oid else None


def list_users(db):
    """All users sans password_hash, sorted — admin pages and /api/admin/users."""
    # password hashes never leave this module — the projection drops the field
    return list(db[USERS].find({}, {"password_hash": 0}).sort("username", 1))


def known_groups(db):
    """Every group name referenced by any user (groups live only on user docs)."""
    # groups exist only as values on user docs; there is no separate collection
    return sorted(db[USERS].distinct("groups"))


def update_user(db, user_id, *, groups=None, is_admin=None, password=None):
    """Patch the given fields on a user; unset fields are left alone."""
    # only the fields the caller passed are touched; an absent password field
    # means "leave it alone", not "clear it"
    changes = {}
    if groups is not None:
        try:
            changes["groups"] = parse_groups(groups)
        except ValueError as exc:
            raise UserError(str(exc)) from exc
    if is_admin is not None:
        changes["is_admin"] = bool(is_admin)
    if password:
        _check_password(password)
        changes["password_hash"] = generate_password_hash(password)
    if changes:
        db[USERS].update_one({"_id": user_id}, {"$set": changes})


def delete_user(db, user_id):
    """Remove the user; any live session of theirs dies in load_user() next request."""
    db[USERS].delete_one({"_id": user_id})
