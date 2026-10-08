import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash, generate_password_hash

from ..db import USERS
from ..permissions import parse_groups

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,49}$")
MIN_PASSWORD_LENGTH = 8


class UserError(ValueError):
    pass


def to_object_id(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def _check_password(password):
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise UserError(f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")


def create_user(db, username, password, groups=(), is_admin=False):
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
    user = db[USERS].find_one({"username": (username or "").strip().lower()})
    if user and check_password_hash(user["password_hash"], password or ""):
        return user
    return None


def get_user(db, user_id):
    oid = to_object_id(user_id)
    return db[USERS].find_one({"_id": oid}) if oid else None


def list_users(db):
    return list(db[USERS].find({}, {"password_hash": 0}).sort("username", 1))


def known_groups(db):
    return sorted(db[USERS].distinct("groups"))


def update_user(db, user_id, *, groups=None, is_admin=None, password=None):
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
    db[USERS].delete_one({"_id": user_id})
