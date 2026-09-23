"""
Module — Agents Library.

Two audiences, one blueprint (small enough not to split, same reasoning as
geography.py/geography_admin.py being separate files instead — here it's
one small file with a clear read/write line instead):

  * index()/request_access() — every tenant's own view: see the catalog,
    see what you already have (or requested, or were denied), request
    something new. Viewing is open to any logged-in user (so a regular User
    understands why an AI-import button is locked); requesting is
    TenantAdmin-only, since granting a teammate can use a feature that
    calls an external AI API is a tenant-level decision, same tier as user
    management (see blueprints/users.py).
  * admin_index()/approve()/deny()/revoke() — the SystemAdmin's queue across
    EVERY tenant. Nothing here is tenant-scoped by design; a SystemAdmin
    has no tenant_id of their own (schema.sql MODULE T).
"""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from auth.decorators import login_required, system_admin_required, tenant_admin_required
from db import get_db, log_action

agents_bp = Blueprint("agents", __name__)


def _catalog_with_status(db, tenant_id):
    """Every active agents_library row THIS TENANT CAN SEE -- a
    platform-wide agent (tenant_id IS NULL) or a custom agent built for
    this tenant specifically (tenant_id = theirs; see schema.sql's
    agents_library.tenant_id comment) -- left-joined with this tenant's
    own tenant_agents row if one exists. status is None (never
    requested), 'Requested', 'Approved', 'Denied', or 'Revoked'."""
    return db.execute(
        """SELECT al.*, ta.tenant_agent_id, ta.status, ta.requested_at, ta.decided_at, ta.notes
           FROM agents_library al
           LEFT JOIN tenant_agents ta ON ta.agent_id = al.agent_id AND ta.tenant_id = ?
           WHERE al.is_active = 1 AND (al.tenant_id IS NULL OR al.tenant_id = ?)
           ORDER BY al.sort_order, al.name COLLATE NOCASE""",
        (tenant_id, tenant_id),
    ).fetchall()


@agents_bp.route("/")
@login_required
def index():
    db = get_db()
    return render_template("agents/index.html", agents=_catalog_with_status(db, g.tenant_id))


@agents_bp.route("/<int:agent_id>/request", methods=["POST"])
@tenant_admin_required
def request_access(agent_id):
    db = get_db()
    # Scoped to what this tenant can actually see (_catalog_with_status's
    # same rule) -- a platform-wide agent, or a custom agent built for
    # THIS tenant -- so a guessed agent_id can't touch another tenant's
    # custom agent.
    agent = db.execute(
        "SELECT * FROM agents_library WHERE agent_id = ? AND is_active = 1 AND (tenant_id IS NULL OR tenant_id = ?)",
        (agent_id, g.tenant_id),
    ).fetchone()
    if agent is None:
        flash("That agent isn't in the library.", "error")
        return redirect(url_for("agents.index"))

    existing = db.execute(
        "SELECT * FROM tenant_agents WHERE tenant_id = ? AND agent_id = ?", (g.tenant_id, agent_id)
    ).fetchone()
    if existing and existing["status"] in ("Requested", "Approved"):
        flash(f"'{agent['name']}' is already {existing['status'].lower()} — nothing to do.", "success")
        return redirect(url_for("agents.index"))

    # A custom agent (agents_library.tenant_id set) was built for this one
    # tenant specifically -- there's no one else's approval to wait on, so
    # it's Approved outright rather than queued for a SystemAdmin (design
    # decision #2, claude/GSS_Agents_Billing_Architecture_v1.md). Every
    # platform-wide agent keeps the normal Requested -> reviewed flow.
    is_custom = agent["tenant_id"] is not None
    status = "Approved" if is_custom else "Requested"

    decided_by = g.user_id if is_custom else None
    decided_at = db.execute("SELECT datetime('now') AS now").fetchone()["now"] if is_custom else None

    if existing:
        # Re-requesting after a Denied/Revoked decision — reset rather
        # than insert a second row (tenant_id, agent_id is UNIQUE),
        # clearing the previous decision so a platform-wide agent's queue
        # entry shows as new again.
        db.execute(
            """UPDATE tenant_agents SET status = ?, requested_by_user_id = ?, requested_at = datetime('now'),
               decided_by_user_id = ?, decided_at = ?, notes = NULL
               WHERE tenant_agent_id = ?""",
            (status, g.user_id, decided_by, decided_at, existing["tenant_agent_id"]),
        )
    else:
        db.execute(
            """INSERT INTO tenant_agents (tenant_id, agent_id, status, requested_by_user_id, decided_by_user_id, decided_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (g.tenant_id, agent_id, status, g.user_id, decided_by, decided_at),
        )
    db.commit()

    if is_custom:
        log_action("Update", "tenant_agents", agent_id, f"Auto-approved custom agent '{agent['name']}'")
        flash(f"'{agent['name']}' is now available — it's a custom agent for your organization.", "success")
    else:
        log_action("Update", "tenant_agents", agent_id, f"Requested access to agent '{agent['name']}'")
        flash(f"Requested access to '{agent['name']}' — a System Admin will review it.", "success")
    return redirect(url_for("agents.index"))


# --------------------------------------------------------------- SystemAdmin

@agents_bp.route("/admin")
@system_admin_required
def admin_index():
    db = get_db()
    rows = db.execute(
        """SELECT ta.*, al.name AS agent_name, al.agent_code, t.tenant_name, t.tenant_code
           FROM tenant_agents ta
           JOIN agents_library al ON al.agent_id = ta.agent_id
           JOIN tenants t ON t.tenant_id = ta.tenant_id
           ORDER BY (ta.status = 'Requested') DESC, ta.requested_at DESC"""
    ).fetchall()
    return render_template("agents/admin.html", rows=rows)


def _get_tenant_agent_or_404(db, tenant_agent_id):
    from flask import abort
    row = db.execute(
        """SELECT ta.*, al.name AS agent_name, t.tenant_name
           FROM tenant_agents ta
           JOIN agents_library al ON al.agent_id = ta.agent_id
           JOIN tenants t ON t.tenant_id = ta.tenant_id
           WHERE ta.tenant_agent_id = ?""",
        (tenant_agent_id,),
    ).fetchone()
    if row is None:
        abort(404)
    return row


@agents_bp.route("/admin/<int:tenant_agent_id>/approve", methods=["POST"])
@system_admin_required
def approve(tenant_agent_id):
    db = get_db()
    row = _get_tenant_agent_or_404(db, tenant_agent_id)
    db.execute(
        "UPDATE tenant_agents SET status = 'Approved', decided_by_user_id = ?, decided_at = datetime('now') WHERE tenant_agent_id = ?",
        (g.user_id, tenant_agent_id),
    )
    db.commit()
    log_action("Update", "tenant_agents", tenant_agent_id,
               f"Approved '{row['tenant_name']}' for agent '{row['agent_name']}'", tenant_id=row["tenant_id"])
    flash(f"Approved '{row['tenant_name']}' for '{row['agent_name']}'.", "success")
    return redirect(url_for("agents.admin_index"))


@agents_bp.route("/admin/<int:tenant_agent_id>/deny", methods=["POST"])
@system_admin_required
def deny(tenant_agent_id):
    db = get_db()
    row = _get_tenant_agent_or_404(db, tenant_agent_id)
    notes = request.form.get("notes", "").strip() or None
    db.execute(
        "UPDATE tenant_agents SET status = 'Denied', decided_by_user_id = ?, decided_at = datetime('now'), notes = ? WHERE tenant_agent_id = ?",
        (g.user_id, notes, tenant_agent_id),
    )
    db.commit()
    log_action("Update", "tenant_agents", tenant_agent_id,
               f"Denied '{row['tenant_name']}' for agent '{row['agent_name']}'", tenant_id=row["tenant_id"])
    flash(f"Denied '{row['tenant_name']}''s request for '{row['agent_name']}'.", "success")
    return redirect(url_for("agents.admin_index"))


@agents_bp.route("/admin/<int:tenant_agent_id>/revoke", methods=["POST"])
@system_admin_required
def revoke(tenant_agent_id):
    """Turns off a previously-Approved agent. Separate from deny() so the
    audit trail and the tenant-facing status text can each read correctly
    ('Denied' reads as 'you asked, we said no'; 'Revoked' reads as 'this
    used to work and no longer does')."""
    db = get_db()
    row = _get_tenant_agent_or_404(db, tenant_agent_id)
    db.execute(
        "UPDATE tenant_agents SET status = 'Revoked', decided_by_user_id = ?, decided_at = datetime('now') WHERE tenant_agent_id = ?",
        (g.user_id, tenant_agent_id),
    )
    db.commit()
    log_action("Update", "tenant_agents", tenant_agent_id,
               f"Revoked '{row['tenant_name']}''s access to agent '{row['agent_name']}'", tenant_id=row["tenant_id"])
    flash(f"Revoked '{row['tenant_name']}''s access to '{row['agent_name']}'.", "success")
    return redirect(url_for("agents.admin_index"))
