"""
Agents Library — helpers shared by every route that gates access behind a
library agent (currently: AI Business Card Import, AI Ad/Listing Import).

See schema.sql's "MODULE AGENTS" comment for the request/approval data
model (agents_library / tenant_agents / agent_usage_log) and
blueprints/agents.py for the TenantAdmin-facing library screen and the
SystemAdmin-facing approval queue.

Billing (cost computation, usage-cap/cycle math, tenant API-key
credentials) lives in agent_billing.py, not here — log_agent_usage() below
delegates to it when a caller supplies model/token info, and
agent_access_required() delegates to it for the usage-cap warning. See
claude/GSS_Agents_Billing_Architecture_v1.md (the project doc) for the
full design.
"""
import functools

from flask import abort, flash, g, redirect, url_for

from db import get_db


def agent_is_approved(db, tenant_id, agent_code: str) -> bool:
    """True only if this tenant has an Approved tenant_agents row for this
    agent. No row at all (never requested), Requested, Denied, and Revoked
    all read as False — the caller doesn't need to tell those apart, only
    the library screen (blueprints/agents.py) does."""
    row = db.execute(
        """SELECT ta.status FROM tenant_agents ta
           JOIN agents_library al ON al.agent_id = ta.agent_id
           WHERE ta.tenant_id = ? AND al.agent_code = ?""",
        (tenant_id, agent_code),
    ).fetchone()
    return row is not None and row["status"] == "Approved"


def log_agent_usage(tenant_id: int, agent_code: str, user_id: int = None, detail: str = None, units: int = 1,
                     model_code: str = None, tokens_input: int = None, tokens_output: int = None):
    """Call this once per SUCCESSFUL agent invocation — e.g. once per
    business-card extraction that actually returns parsed data, once per
    ad photo Claude successfully reads. Do not call this for a failed/
    errored attempt (a bad photo, a Claude API error) — see the four call
    sites in blueprints/data_exchange.py and blueprints/organizations.py.

    model_code/tokens_input/tokens_output are optional — pass them (every
    real call site does, using the extraction module's own EXTRACTION_MODEL
    constant and the usage dict its extract_*() function now returns) and
    this also resolves the model, the tenant's own active credential for
    that model's provider (if any), and the actual dollar cost via
    agent_billing.py, storing all of it on the agent_usage_log row for the
    profit/loss report. Omit them (or if the model isn't in the ai_models
    catalog yet) and the row is still logged, just without those figures —
    usage logging is never worth breaking the feature it's logging over.

    Silently does nothing at all if agent_code isn't in the catalog
    (shouldn't happen outside of a coding mistake)."""
    db = get_db()
    agent = db.execute("SELECT agent_id FROM agents_library WHERE agent_code = ?", (agent_code,)).fetchone()
    if agent is None:
        return

    model_id = None
    credential_id = None
    actual_cost = None
    if model_code:
        import agent_billing
        model_id = agent_billing.resolve_model_id(db, model_code)
        if model_id is not None:
            credential_id = agent_billing.resolve_active_credential(db, tenant_id, model_id)
            actual_cost = agent_billing.compute_cost(db, model_id, tokens_input, tokens_output)

    db.execute(
        """INSERT INTO agent_usage_log
           (tenant_id, agent_id, user_id, units, detail, model_id, credential_id, tokens_input, tokens_output, actual_cost)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tenant_id, agent["agent_id"], user_id, units, detail, model_id, credential_id, tokens_input, tokens_output, actual_cost),
    )
    if credential_id is not None:
        db.execute("UPDATE tenant_model_credentials SET last_used_at = datetime('now') WHERE credential_id = ?", (credential_id,))
    db.commit()


def agent_access_required(agent_code: str):
    """Route decorator: blocks the view unless the current tenant has been
    Approved for `agent_code`, redirecting to the Agents Library instead of
    a bare 403 — "not yet turned on for your organization" is an expected,
    self-service-fixable state (click Request Access), not an error page.

    Requires @login_required to already have run (reads g.tenant_id) — put
    this decorator BELOW @login_required:

        @some_bp.route(...)
        @login_required
        @agent_access_required("business_card_import")
        def view(...): ...
    """
    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            db = get_db()
            if not agent_is_approved(db, g.tenant_id, agent_code):
                flash(
                    "This feature is part of the Agents Library and isn't turned on for your "
                    "organization yet. Request access below and a System Admin will review it.",
                    "error",
                )
                return redirect(url_for("agents.index"))

            # Advance notice only -- never blocks the run (see design
            # decision #1, claude/GSS_Agents_Billing_Architecture_v1.md).
            # Flashed here so it shows on the form page AND is repeated
            # before every subsequent run once the tenant is at/past 90%
            # of their flat-monthly plan's included-units cap for this
            # agent this billing cycle.
            import agent_billing
            warning = agent_billing.cycle_usage_warning(db, g.tenant_id, agent_code)
            if warning:
                flash(warning, "warning")

            return view(*args, **kwargs)
        return wrapped
    return decorator
