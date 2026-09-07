import functools

from flask import abort, flash, g, redirect, session, url_for

from security import session_keys


def get_current_dek():
    """The unwrapped field-encryption key for the CURRENT TENANT, for this
    session, or None if not logged in. Shared by every user of that tenant —
    see schema.sql MODULE T and security/crypto.py."""
    token = session.get("auth_token")
    if not token:
        return None
    return session_keys.get(token)


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        dek = get_current_dek()
        if dek is None:
            # The session cookie may still carry an auth_token (e.g. the dev
            # server's --debug auto-reloader restarted the process and wiped
            # the in-memory session_keys store, but the signed cookie itself
            # survives since it's backed by the on-disk secret key). Clearing
            # the session here keeps the "logged in" flag and the actual
            # login state in sync.
            session.clear()
            return redirect(url_for("auth_bp.login"))
        g.dek = dek
        g.tenant_id = session.get("tenant_id")
        g.user_id = session.get("user_id")
        g.username = session.get("username")
        g.display_name = session.get("display_name")
        g.role = session.get("role")
        g.tenant_name = session.get("tenant_name")
        return view(*args, **kwargs)
    return wrapped


def tenant_admin_required(view):
    """Like login_required, but also requires the TenantAdmin or SystemAdmin
    role. Use for user-management/whole-tenant screens."""
    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.role not in ("TenantAdmin", "SystemAdmin"):
            flash("That page is restricted to Tenant Admins.", "error")
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def system_admin_required(view):
    """Like login_required, but also requires the SystemAdmin role (tenant
    provisioning, whole-database backups). SystemAdmin accounts have no
    tenant_id/DEK of their own, so pages behind this decorator must not rely
    on g.dek."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        token = session.get("auth_token")
        if not token or session.get("role") != "SystemAdmin":
            session.clear()
            return redirect(url_for("auth_bp.login"))
        g.user_id = session.get("user_id")
        g.username = session.get("username")
        g.role = session.get("role")
        return view(*args, **kwargs)
    return wrapped
