from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from ..db import get_db
from .users import authenticate, get_user

bp = Blueprint("auth", __name__)


@bp.before_app_request
def load_user():
    g.user = None
    user_id = session.get("user_id")
    if user_id and request.endpoint != "static":
        g.user = get_user(get_db(), user_id)
        if g.user is None:
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.is_json:
                return {"error": "Your session expired. Please sign in again."}, 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _safe_next(target):
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return url_for("chat.index")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = authenticate(get_db(), request.form.get("username"), request.form.get("password"))
        if user:
            session.clear()
            session["user_id"] = str(user["_id"])
            return redirect(_safe_next(request.args.get("next")))
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
