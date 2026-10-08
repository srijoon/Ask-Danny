# CSRF protection for the whole app: a per-session token that forms and fetch()
# calls must echo back on mutating requests. Installed by create_app as a
# before_request hook; templates get the token via the csrf_token() Jinja global.
import hmac
import secrets

from flask import abort, current_app, request, session

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def csrf_token():
    """Return this session's CSRF token, minting one on first use."""
    # lazily minted per session, so pages that never render a form never write a cookie
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def init_app(app):
    """Expose csrf_token() to templates and install the request hook below."""
    # templates embed the token in hidden inputs; the API returns it from /api/csrf
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def check_csrf():
        """Reject mutating requests whose token doesn't match the session's."""
        # only mutating verbs are checked; a forged cross-site GET can't change state
        if not current_app.config["CSRF_ENABLED"] or request.method not in _UNSAFE_METHODS:
            return
        # form posts send csrf_token; fetch() clients send the header instead
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("_csrf", "")
        # compare_digest avoids leaking the token through comparison timing
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, description="Your session expired or the form is stale. Reload and try again.")
