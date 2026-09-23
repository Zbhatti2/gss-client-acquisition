"""
Module — Agent Billing.

Two audiences, one blueprint (same split as blueprints/agents.py):

  * usage()/api_keys()/add_api_key()/deactivate_api_key() — every tenant's
    own view: usage-vs-cap for whatever agents they're Approved for (no
    actual cost or margin shown — see the design doc's "clients don't
    relate to per-token cost"), and TenantAdmin-only management of the
    tenant's own provider API key. Adding a key requires g.dek (the
    tenant's field-encryption key), same as any other encrypted column —
    see security/crypto.py.
  * admin_catalog()/admin_update_plan()/admin_add_rate()/admin_tenant_report() —
    the SystemAdmin's platform-wide view: the agent/model/pricing catalog
    (editable), and a per-tenant usage/billed/actual-cost/margin report —
    the profit/loss computation the design doc calls for.

See agent_billing.py for the cost/cap/credential logic this blueprint is a
thin UI layer over, and claude/GSS_Agents_Billing_Architecture_v1.md (the
project doc) for the full design and the decisions locked in before this
was built.
"""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

import agent_billing
from auth.decorators import login_required, system_admin_required, tenant_admin_required
from db import get_db, log_action

billing_bp = Blueprint("billing", __name__)


# --------------------------------------------------------------- tenant-facing

@billing_bp.route("/usage")
@login_required
def usage():
    """Every agent this tenant is Approved for: this billing cycle's usage
    against the plan's included-units cap. Deliberately does NOT show
    actual_cost or margin — that's internal, see the SystemAdmin report
    below for that."""
    db = get_db()
    rows = db.execute(
        """SELECT ta.subscribed_at, al.agent_id, al.name AS agent_name, al.agent_code,
                  pp.plan_name, pp.pricing_model, pp.included_units_per_cycle,
                  pp.overage_unit_fee, pp.flat_fee_amount, pp.per_transaction_fee, pp.currency
           FROM tenant_agents ta
           JOIN agents_library al ON al.agent_id = ta.agent_id
           LEFT JOIN agent_pricing_plans pp ON pp.plan_id = ta.pricing_plan_id
           WHERE ta.tenant_id = ? AND ta.status = 'Approved'
           ORDER BY al.name COLLATE NOCASE""",
        (g.tenant_id,),
    ).fetchall()

    usage_rows = []
    for r in rows:
        cycle_start, cycle_end = agent_billing.current_cycle_bounds(r["subscribed_at"])
        used = agent_billing.usage_this_cycle(db, g.tenant_id, r["agent_id"], cycle_start, cycle_end)
        cap = r["included_units_per_cycle"]
        usage_rows.append({
            "row": r,
            "used": used,
            "cycle_start": cycle_start,
            "cycle_end": cycle_end,
            "pct": int(used / cap * 100) if cap else None,
        })
    return render_template("billing/usage.html", usage_rows=usage_rows)


@billing_bp.route("/api-keys")
@tenant_admin_required
def api_keys():
    db = get_db()
    credentials = agent_billing.list_credentials(db, g.tenant_id)
    providers = db.execute(
        "SELECT * FROM ai_providers WHERE is_active = 1 ORDER BY name COLLATE NOCASE"
    ).fetchall()
    return render_template("billing/api_keys.html", credentials=credentials, providers=providers,
                           mask_key=agent_billing.mask_key)


@billing_bp.route("/api-keys/add", methods=["POST"])
@tenant_admin_required
def add_api_key():
    db = get_db()
    provider_code = request.form.get("provider_code", "").strip()
    api_key = request.form.get("api_key", "").strip()
    label = request.form.get("label", "").strip()
    try:
        agent_billing.save_credential(db, g.dek, g.tenant_id, provider_code, api_key, label, g.user_id)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("billing.api_keys"))
    log_action("Create", "tenant_model_credentials", None, f"Added a {provider_code} API key")
    flash("API key saved.", "success")
    return redirect(url_for("billing.api_keys"))


@billing_bp.route("/api-keys/<int:credential_id>/deactivate", methods=["POST"])
@tenant_admin_required
def deactivate_api_key(credential_id):
    db = get_db()
    agent_billing.deactivate_credential(db, g.tenant_id, credential_id)
    log_action("Update", "tenant_model_credentials", credential_id, "Deactivated an API key")
    flash("Key deactivated.", "success")
    return redirect(url_for("billing.api_keys"))


# ----------------------------------------------------------------- SystemAdmin

@billing_bp.route("/admin/catalog")
@system_admin_required
def admin_catalog():
    db = get_db()
    agents = db.execute(
        """SELECT al.*, m.display_name AS default_model_name, t.tenant_name AS custom_for_tenant
           FROM agents_library al
           LEFT JOIN ai_models m ON m.model_id = al.default_model_id
           LEFT JOIN tenants t ON t.tenant_id = al.tenant_id
           ORDER BY al.sort_order, al.name COLLATE NOCASE"""
    ).fetchall()
    plans = db.execute(
        """SELECT pp.*, al.name AS agent_name FROM agent_pricing_plans pp
           JOIN agents_library al ON al.agent_id = pp.agent_id
           ORDER BY al.name COLLATE NOCASE, pp.plan_name COLLATE NOCASE"""
    ).fetchall()
    models = db.execute(
        """SELECT m.*, p.name AS provider_name FROM ai_models m
           JOIN ai_providers p ON p.provider_id = m.provider_id
           ORDER BY p.name COLLATE NOCASE, m.sort_order"""
    ).fetchall()
    rates = db.execute(
        """SELECT r.*, m.display_name AS model_name FROM ai_model_rates r
           JOIN ai_models m ON m.model_id = r.model_id
           ORDER BY m.display_name COLLATE NOCASE, r.effective_from DESC"""
    ).fetchall()
    tenants = db.execute(
        "SELECT tenant_id, tenant_name FROM tenants WHERE is_platform = 0 ORDER BY tenant_name COLLATE NOCASE"
    ).fetchall()
    return render_template("billing/admin_catalog.html", agents=agents, plans=plans, models=models, rates=rates,
                           tenants=tenants)


@billing_bp.route("/admin/catalog/plan/<int:plan_id>", methods=["POST"])
@system_admin_required
def admin_update_plan(plan_id):
    db = get_db()
    plan = db.execute("SELECT * FROM agent_pricing_plans WHERE plan_id = ?", (plan_id,)).fetchone()
    if plan is None:
        abort(404)

    def _num(name):
        raw = (request.form.get(name) or "").strip()
        return float(raw) if raw else None

    def _int(name):
        raw = (request.form.get(name) or "").strip()
        return int(raw) if raw else None

    db.execute(
        """UPDATE agent_pricing_plans SET flat_fee_amount = ?, included_units_per_cycle = ?,
           overage_unit_fee = ?, per_transaction_fee = ?, is_active = ? WHERE plan_id = ?""",
        (_num("flat_fee_amount"), _int("included_units_per_cycle"), _num("overage_unit_fee"),
         _num("per_transaction_fee"), 1 if request.form.get("is_active") else 0, plan_id),
    )
    db.commit()
    log_action("Update", "agent_pricing_plans", plan_id, f"Updated pricing plan '{plan['plan_name']}'")
    flash(f"Updated '{plan['plan_name']}'.", "success")
    return redirect(url_for("billing.admin_catalog"))


@billing_bp.route("/admin/catalog/rate", methods=["POST"])
@system_admin_required
def admin_add_rate():
    """Records a NEW dated rate row for a model rather than editing the
    latest one in place — see schema.sql's ai_model_rates comment: a past
    agent_usage_log row's actual_cost was computed and stored at the time,
    so a price correction here only changes what a FUTURE call costs, it
    never rewrites history."""
    db = get_db()
    model_id = request.form.get("model_id", type=int)
    effective_from = (request.form.get("effective_from") or "").strip()
    cost_in = request.form.get("cost_per_1k_input_tokens", type=float)
    cost_out = request.form.get("cost_per_1k_output_tokens", type=float)
    model = db.execute("SELECT * FROM ai_models WHERE model_id = ?", (model_id,)).fetchone()
    if model is None or not effective_from or cost_in is None or cost_out is None:
        flash("Model, effective date, and both per-1K rates are required.", "error")
        return redirect(url_for("billing.admin_catalog"))
    db.execute(
        "INSERT INTO ai_model_rates (model_id, effective_from, cost_per_1k_input_tokens, cost_per_1k_output_tokens) "
        "VALUES (?, ?, ?, ?)",
        (model_id, effective_from, cost_in, cost_out),
    )
    db.commit()
    log_action("Create", "ai_model_rates", model_id, f"New rate for '{model['display_name']}' effective {effective_from}")
    flash(f"Recorded a new rate for '{model['display_name']}' effective {effective_from}.", "success")
    return redirect(url_for("billing.admin_catalog"))


@billing_bp.route("/admin/tenant/<int:tenant_id>")
@system_admin_required
def admin_tenant_report(tenant_id):
    """Profit/loss: for each agent this tenant is Approved for, this
    cycle's usage, what they're billed under their plan, the real
    actual_cost logged, and the margin between them."""
    db = get_db()
    tenant = db.execute("SELECT * FROM tenants WHERE tenant_id = ? AND is_platform = 0", (tenant_id,)).fetchone()
    if tenant is None:
        abort(404)

    subs = db.execute(
        """SELECT ta.subscribed_at, al.agent_id, al.name AS agent_name,
                  pp.plan_name, pp.pricing_model, pp.included_units_per_cycle,
                  pp.overage_unit_fee, pp.flat_fee_amount, pp.per_transaction_fee, pp.currency
           FROM tenant_agents ta
           JOIN agents_library al ON al.agent_id = ta.agent_id
           LEFT JOIN agent_pricing_plans pp ON pp.plan_id = ta.pricing_plan_id
           WHERE ta.tenant_id = ? AND ta.status = 'Approved'
           ORDER BY al.name COLLATE NOCASE""",
        (tenant_id,),
    ).fetchall()

    report_rows = []
    for r in subs:
        cycle_start, cycle_end = agent_billing.current_cycle_bounds(r["subscribed_at"])
        used = agent_billing.usage_this_cycle(db, tenant_id, r["agent_id"], cycle_start, cycle_end)
        billed = agent_billing.compute_billed_amount(r, used)
        actual = db.execute(
            "SELECT COALESCE(SUM(actual_cost), 0) AS total FROM agent_usage_log "
            "WHERE tenant_id = ? AND agent_id = ? AND used_at >= ? AND used_at < ?",
            (tenant_id, r["agent_id"],
             cycle_start.strftime("%Y-%m-%d %H:%M:%S"), cycle_end.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()["total"] or 0
        report_rows.append({
            "agent_name": r["agent_name"],
            "plan_name": r["plan_name"] or "(no plan chosen)",
            "currency": r["currency"] or "USD",
            "used": used,
            "cycle_start": cycle_start,
            "cycle_end": cycle_end,
            "billed": billed,
            "actual_cost": round(actual, 4),
            "margin": round(billed - actual, 4) if billed is not None else None,
        })

    tenants = db.execute(
        "SELECT tenant_id, tenant_name FROM tenants WHERE is_platform = 0 ORDER BY tenant_name COLLATE NOCASE"
    ).fetchall()
    return render_template("billing/admin_tenant_report.html", tenant=tenant, report_rows=report_rows, tenants=tenants)
