"""
Minimal manual CSRF protection (no Flask-WTF dependency — kept out of
requirements.txt deliberately). Every form includes a hidden csrf_token
field; every POST is checked against the token stored in the signed session
cookie.
"""
import secrets

from flask import abort, request, session


# Endpoints (as "blueprint_name.view_func_name", the same string Flask's
# routing exposes as request.endpoint) exempted from the check below. CSRF
# protection exists to stop a malicious page from riding a logged-in user's
# SESSION COOKIE into a state-changing request on their behalf; an endpoint
# that isn't authenticated via the GSS session cookie in the first place has
# nothing for CSRF to exploit, so exempting it is correct rather than a
# hole. Keep this list short, and comment each entry with why it qualifies.
CSRF_EXEMPT_ENDPOINTS = {
    # Public lead-intake form (blueprints/public_leads.py) -- reached by a
    # tenant's own public marketing website via a cross-origin fetch(), and
    # authenticated by that tenant's opaque lead_intake_token carried in the
    # JSON body, never by a GSS session cookie (the browser submitting it
    # has typically never logged into GSS, or is logged into a different
    # tenant's session entirely).
    "public_leads.submit_lead",
}


def get_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def validate_csrf():
    token = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not expected or not secrets.compare_digest(token, expected):
        abort(400, description="Invalid or missing CSRF token — please retry the form.")


def init_app(app):
    app.jinja_env.globals["csrf_token"] = get_csrf_token

    @app.before_request
    def _check_csrf():
        if request.method == "POST" and request.endpoint not in CSRF_EXEMPT_ENDPOINTS:
            validate_csrf()
