"""
Agents/Models billing — cost computation, usage-cycle/cap math, and tenant
API-key (credential) management, on top of the Agents Library
(agents_library / tenant_agents / agent_usage_log, see agents.py) and the
model catalog (ai_providers / ai_models / ai_model_rates) and pricing
(agent_pricing_plans / tenant_model_credentials) added in db.py's
_migration_agents_billing. Full design rationale:
claude/GSS_Agents_Billing_Architecture_v1.md (the project doc).

Three groups of functions:
  * Cost:        resolve_model_id, resolve_active_credential, compute_cost
                 -- called from agents.log_agent_usage() on every successful
                 agent invocation, so agent_usage_log carries the real
                 tokens/cost/model/credential for a profit/loss report.
  * Cap/cycle:   current_cycle_bounds, usage_this_cycle, cycle_usage_warning,
                 compute_billed_amount -- the monthly-cycle math shared by
                 the tenant-facing usage warning (agents.agent_access_required)
                 and the SystemAdmin profit/loss report (blueprints/billing.py).
                 Policy (design decision #1): usage is NEVER blocked once a
                 flat-monthly plan's cap is crossed -- overage is billed, not
                 gated -- only a warning is shown, starting at 90% of the cap
                 and repeated before every run until the cycle resets.
  * Credentials: list_credentials, save_credential, deactivate_credential,
                 mask_key -- a tenant's own provider API key, encrypted
                 under that tenant's DEK (security/crypto.py), for a model
                 that requires one (ai_models.requires_tenant_api_key).
                 Independent of pricing plan (design principle: subscription
                 and credential are orthogonal).
"""
import calendar
from datetime import datetime

CAP_WARNING_THRESHOLD = 0.90


# --------------------------------------------------------------------- cost

def resolve_model_id(db, model_code: str):
    """ai_models.model_id for a model_code (e.g. 'claude-sonnet-5'), or None
    if it isn't in the catalog yet -- callers should still log usage
    without a model_id/cost rather than fail the caller's actual feature."""
    if not model_code:
        return None
    row = db.execute("SELECT model_id FROM ai_models WHERE model_code = ?", (model_code,)).fetchone()
    return row["model_id"] if row else None


def resolve_active_credential(db, tenant_id: int, model_id: int):
    """The tenant's own active tenant_model_credentials.credential_id for
    the PROVIDER behind this model, or None if they have none (meaning the
    call used the platform's shared key). A tenant can have at most one
    active credential per provider (schema.sql's partial unique index), so
    this is unambiguous."""
    if model_id is None:
        return None
    row = db.execute(
        """SELECT c.credential_id FROM tenant_model_credentials c
           JOIN ai_models m ON m.provider_id = c.provider_id
           WHERE c.tenant_id = ? AND m.model_id = ? AND c.is_active = 1""",
        (tenant_id, model_id),
    ).fetchone()
    return row["credential_id"] if row else None


def get_current_rate(db, model_id: int, at: str = None):
    """The ai_model_rates row in force at `at` (a 'YYYY-MM-DD[ HH:MM:SS]'
    string, default now) for this model -- the row with the latest
    effective_from that isn't after `at`. None if the model has no rate
    seeded yet."""
    if model_id is None:
        return None
    at = at or db.execute("SELECT datetime('now') AS now").fetchone()["now"]
    return db.execute(
        "SELECT * FROM ai_model_rates WHERE model_id = ? AND effective_from <= ? ORDER BY effective_from DESC LIMIT 1",
        (model_id, at),
    ).fetchone()


def compute_cost(db, model_id: int, tokens_input, tokens_output, at: str = None):
    """actual_cost in the rate's currency, or None if model_id/token counts
    aren't known or no rate is on file -- a missing cost is left NULL in
    agent_usage_log rather than guessed at, so a profit/loss report can
    tell "no data" apart from "genuinely free."."""
    if model_id is None or tokens_input is None or tokens_output is None:
        return None
    rate = get_current_rate(db, model_id, at)
    if rate is None:
        return None
    cost = (tokens_input / 1000.0) * rate["cost_per_1k_input_tokens"] + \
           (tokens_output / 1000.0) * rate["cost_per_1k_output_tokens"]
    return round(cost, 6)


# ---------------------------------------------------------------- cap/cycle

def _parse_dt(value):
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) > 10:
            return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _add_months(dt: datetime, months: int) -> datetime:
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def current_cycle_bounds(subscribed_at, now: datetime = None):
    """(cycle_start, cycle_end) datetimes for the monthly usage cycle a
    tenant_agents row's cap/warning/billing is measured against, anchored
    to the day-of-month of `subscribed_at` (clamped to whatever month it
    lands in -- e.g. subscribed on the 31st runs a short cycle in
    February). Falls back to the calendar month if subscribed_at is unset
    (a row from before pricing plans existed, or one with no plan yet)."""
    now = now or datetime.utcnow()
    anchor = _parse_dt(subscribed_at)
    if anchor is None:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, _add_months(start, 1)
    day = anchor.day
    candidate = now.replace(day=min(day, calendar.monthrange(now.year, now.month)[1]),
                             hour=0, minute=0, second=0, microsecond=0)
    if candidate > now:
        candidate = _add_months(candidate, -1)
    return candidate, _add_months(candidate, 1)


def usage_this_cycle(db, tenant_id: int, agent_id: int, cycle_start: datetime, cycle_end: datetime) -> int:
    """SUM(units) logged for this tenant+agent within [cycle_start, cycle_end)
    -- units is what counts against a plan's cap/per-transaction fee (see
    schema.sql's agent_usage_log comment)."""
    row = db.execute(
        "SELECT COALESCE(SUM(units), 0) AS total FROM agent_usage_log "
        "WHERE tenant_id = ? AND agent_id = ? AND used_at >= ? AND used_at < ?",
        (tenant_id, agent_id,
         cycle_start.strftime("%Y-%m-%d %H:%M:%S"), cycle_end.strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchone()
    return row["total"]


def _tenant_agent_plan_row(db, tenant_id: int, agent_code: str):
    return db.execute(
        """SELECT ta.subscribed_at, al.agent_id, al.name AS agent_name,
                  pp.pricing_model, pp.included_units_per_cycle, pp.overage_unit_fee, pp.currency
           FROM tenant_agents ta
           JOIN agents_library al ON al.agent_id = ta.agent_id
           LEFT JOIN agent_pricing_plans pp ON pp.plan_id = ta.pricing_plan_id
           WHERE ta.tenant_id = ? AND al.agent_code = ? AND ta.status = 'Approved'""",
        (tenant_id, agent_code),
    ).fetchone()


def cycle_usage_warning(db, tenant_id: int, agent_code: str):
    """A warning message once this tenant has reached 90% of their
    flat_monthly plan's included_units_per_cycle for this agent THIS
    cycle, else None. Shown before every run from 90% onward (not just
    once) -- see agents.agent_access_required. Never a reason to block a
    run (design decision #1): a per_transaction plan, an agent with no
    plan chosen yet, or a flat_monthly plan under 90% all return None
    here, and the agent keeps working past the cap regardless of what
    this returns."""
    row = _tenant_agent_plan_row(db, tenant_id, agent_code)
    if row is None or row["pricing_model"] != "flat_monthly" or not row["included_units_per_cycle"]:
        return None

    cycle_start, cycle_end = current_cycle_bounds(row["subscribed_at"])
    used = usage_this_cycle(db, tenant_id, row["agent_id"], cycle_start, cycle_end)
    cap = row["included_units_per_cycle"]
    if used < cap * CAP_WARNING_THRESHOLD:
        return None

    currency = row["currency"] or "USD"
    overage_fee = row["overage_unit_fee"]
    if used >= cap:
        if overage_fee:
            return (f"“{row['agent_name']}”: you've used {used} of {cap} included queries this "
                     f"billing cycle and are now in overage — each additional query is billed at "
                     f"{currency} {overage_fee:.2f}.")
        return (f"“{row['agent_name']}”: you've used {used} of {cap} included queries this "
                f"billing cycle. Usage beyond the included amount isn't separately priced on your "
                f"current plan.")

    pct = int(used / cap * 100)
    overage_note = (f" Once you reach the cap, additional queries are billed at {currency} "
                     f"{overage_fee:.2f} each.") if overage_fee else ""
    return (f"“{row['agent_name']}”: you've used {used} of {cap} included queries this billing "
            f"cycle ({pct}%).{overage_note}")


def compute_billed_amount(plan_row, units: int):
    """What a tenant owes for `units` uses of an agent under `plan_row` (an
    agent_pricing_plans row/dict) this cycle. None if there's no plan at
    all yet. Used by the SystemAdmin profit/loss report (blueprints/
    billing.py) -- runtime access is never gated by this number (see
    cycle_usage_warning)."""
    if plan_row is None:
        return None
    if plan_row["pricing_model"] == "per_transaction":
        return round((plan_row["per_transaction_fee"] or 0) * units, 2)
    if plan_row["pricing_model"] == "flat_monthly":
        total = plan_row["flat_fee_amount"] or 0
        cap = plan_row["included_units_per_cycle"]
        if cap is not None and units > cap and plan_row["overage_unit_fee"]:
            total += (units - cap) * plan_row["overage_unit_fee"]
        return round(total, 2)
    return None


# ----------------------------------------------------------------- credentials

def mask_key(plaintext: str) -> str:
    """'sk-ant-...9f2a' style masking for display -- never show a stored
    key in full again once saved."""
    if not plaintext:
        return ""
    tail = plaintext[-4:]
    return f"{'•' * 8}{tail}"


def list_credentials(db, tenant_id: int):
    return db.execute(
        """SELECT c.*, p.name AS provider_name, p.provider_code
           FROM tenant_model_credentials c
           JOIN ai_providers p ON p.provider_id = c.provider_id
           WHERE c.tenant_id = ?
           ORDER BY p.name COLLATE NOCASE, c.is_active DESC, c.added_at DESC""",
        (tenant_id,),
    ).fetchall()


def save_credential(db, dek: bytes, tenant_id: int, provider_code: str, api_key: str, label: str, user_id: int):
    """Adds a new ACTIVE credential for (tenant_id, provider_code),
    deactivating any previously active one for that provider first (only
    one active credential per provider at a time -- schema.sql's partial
    unique index, design decision #3). The previous row is kept, just
    flipped inactive rather than deleted, so it stays visible as history
    and nothing here is a destructive overwrite. Raises ValueError if
    provider_code isn't in the catalog or api_key is blank."""
    from security import crypto

    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("API key is required.")
    provider = db.execute("SELECT provider_id FROM ai_providers WHERE provider_code = ?", (provider_code,)).fetchone()
    if provider is None:
        raise ValueError(f"Unknown provider {provider_code!r}.")

    db.execute(
        "UPDATE tenant_model_credentials SET is_active = 0 WHERE tenant_id = ? AND provider_id = ? AND is_active = 1",
        (tenant_id, provider["provider_id"]),
    )
    wrapped = crypto.encrypt_value(api_key, dek)
    db.execute(
        "INSERT INTO tenant_model_credentials (tenant_id, provider_id, api_key_wrapped, label, added_by_user_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (tenant_id, provider["provider_id"], wrapped, (label or "").strip() or None, user_id),
    )
    db.commit()


def deactivate_credential(db, tenant_id: int, credential_id: int):
    db.execute(
        "UPDATE tenant_model_credentials SET is_active = 0 WHERE tenant_id = ? AND credential_id = ?",
        (tenant_id, credential_id),
    )
    db.commit()
