# HTML login/logout plus the decorators everything else relies on:
# login_required (JSON 401 for /api, redirect for pages) and admin_required.
# load_user() resolves the session cookie to g.user once per request.
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from ..db import get_db
from .users import authenticate, get_user

bp = Blueprint("auth", __name__)


@bp.before_app_request
def load_user():
    """Resolve the session's user_id into g.user once per request."""
    # resolves the session cookie to a user doc once per request; every view then
    # just reads g.user instead of re-querying
    g.user = None
    user_id = session.get("user_id")
    if user_id and request.endpoint != "static":
        g.user = get_user(get_db(), user_id)
        if g.user is None:
            # the account was deleted while the session was still valid
            session.clear()


def login_required(view):
    """Require a signed-in user: JSON 401 for /api requests, login redirect for pages."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        """Send anonymous callers to 401/redirect, else run the view."""
        if g.user is None:
            # API clients (including plain GETs to /api) need a 401 they can handle,
            # not a redirect to the HTML login page
            if request.is_json or request.blueprint == "api":
                return {"error": "Your session expired. Please sign in again."}, 401
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """login_required plus an is_admin check — admin pages and /api/admin/*."""
    @wraps(view)
    @login_required  # nested, so g.user is guaranteed set when is_admin is checked
    def wrapped(*args, **kwargs):
        """403 for signed-in non-admins, else run the view."""
        if not g.user.get("is_admin"):
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _safe_next(target):
    """Allow only same-site paths for the post-login redirect, else the chat page."""
    # browsers drop tabs/newlines, so "/\t/evil.com" would turn into "//evil.com"
    if (target and target.startswith("/") and not target.startswith("//") and "\\" not in target
            and target.isprintable()):
        return target
    return url_for("chat.index")


@bp.route("/login", methods=["GET", "POST"])
def login():
    """HTML login form; JSON clients use /api/login instead — same session either way."""
    if request.method == "POST":
        user = authenticate(get_db(), request.form.get("username"), request.form.get("password"))
        if user:
            # drop any pre-login session state (old CSRF token, stale data) before
            # attaching the identity
            session.clear()
            session["user_id"] = str(user["_id"])
            return redirect(_safe_next(request.args.get("next")))
        # vague on purpose: don't reveal whether the username or the password was wrong
        flash("Wrong username or password.", "error")
    return render_template("login.html")


@bp.post("/logout")
def logout():
    """Clear the session and return to the login page (API clients use /api/logout)."""
    session.clear()
    return redirect(url_for("auth.login"))
