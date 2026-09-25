"""
Module — Client Acquisition (sales pipeline / CRM).

Tracks a prospective client's journey — an Opportunity — through a
tenant's own Pipeline Template (a named sequence of stages, each with a
typical time window, a checklist of required actions, and a pre-defined
outreach cadence). An Opportunity links to EXISTING organizations/contacts
rows; there is no separate "clients" table (see the
GSS_Data_Model_Decisions_v1.md project doc's Client Acquisition addendum
for the full set of decisions this module implements, built from the
source document GSS_Sales_Cycle_Module-New-1a.pdf).

"Customer Service" (customer complaints/tickets/delivery) is a deliberately
separate, not-yet-built module — see blueprints/customer_service.py's
"coming soon" placeholder. Closing an Opportunity here (close_opportunity)
only stubs that handoff.

Controlled vocabularies (CHANNELS/DIRECTIONS/OUTCOMES/CONTACT_ROLES/
NURTURE_REASONS/LOST_REASONS/TASK_SOURCES below) are FIXED, mirroring the
CHECK constraints on the underlying tables in schema.sql's "MODULE — CLIENT
ACQUISITION" section — NOT tenant-editable Table Maintenance lookups. Keep
these two lists in sync by hand, same convention as every other fixed
vocabulary in this app (e.g. contact_phones.phone_type).

Risk flags (stalled/aging/ghosted/blocked) are computed on the fly by
_risk_flags() below, never persisted — matching the project doc's own
"dashboards computed from Opportunities + interactions + checklist_
progress" and "risk flags are auto-generated, not manually entered" rules.
The specific thresholds (STALLED_NO_INTERACTION_DAYS, GHOSTED_ATTEMPT_
COUNT) are this module's own reasonable defaults, not values pulled from
the source PDF — tune them here if they don't match how the team actually
works.
"""
import functools

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for

from auth.decorators import get_current_dek, login_required
from db import get_db, log_action

client_acquisition_bp = Blueprint("client_acquisition", __name__)

# Keep in sync with schema.sql's CHECK constraints on interactions.channel /
# pipeline_template_cadence_steps.channel / tasks.channel.
CHANNELS = ["Call", "Email", "LinkedIn", "Text", "In-Person", "Mail", "Video", "Note"]
DIRECTIONS = ["Outbound", "Inbound", "Internal"]
OUTCOMES = [
    "Connected", "Left Voicemail", "No Answer", "Meeting Scheduled", "Meeting Held",
    "Proposal Sent", "Follow-Up Needed", "Referred Internally", "Not Interested",
    "Requested Callback", "Gatekeeper", "Wrong Contact", "Rescheduled", "Other",
]
CONTACT_ROLES = ["Economic Buyer", "Champion", "Influencer", "Blocker", "Decision Maker", "End User"]
NURTURE_REASONS = ["Timing", "Budget Cycle", "Internal Change", "Rebrand", "Hiring Freeze", "Other"]
LOST_REASONS = ["Price", "Competitor", "Timing", "No Budget", "No Authority", "No Need", "Unresponsive", "Out of Scope"]
TASK_SOURCES = ["Cadence", "Manual", "Nurture Revisit"]

STALLED_NO_INTERACTION_DAYS = 14
GHOSTED_ATTEMPT_COUNT = 3


# ----------------------------------------------------------------- helpers

def _int_or_none(value):
    value = (value or "").strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _float_or_none(value):
    value = (value or "").strip()
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _now(db):
    return db.execute("SELECT datetime('now') n").fetchone()["n"]


def _organizations(db):
    return db.execute(
        "SELECT organization_id, organization_name FROM organizations WHERE tenant_id = ? ORDER BY organization_name COLLATE NOCASE",
        (g.tenant_id,),
    ).fetchall()


def _templates(db):
    return db.execute(
        "SELECT * FROM pipeline_templates WHERE tenant_id = ? AND is_active = 1 ORDER BY sort_order, template_name COLLATE NOCASE",
        (g.tenant_id,),
    ).fetchall()


def _tenant_users(db):
    return db.execute(
        "SELECT user_id, display_name FROM users WHERE tenant_id = ? AND is_active = 1 ORDER BY display_name COLLATE NOCASE",
        (g.tenant_id,),
    ).fetchall()


def _get_opportunity(db, opp_id):
    opp = db.execute(
        """SELECT o.*, org.organization_name, pt.template_name, u.display_name AS assigned_user_name
           FROM opportunities o
           JOIN organizations org ON org.organization_id = o.organization_id
           JOIN pipeline_templates pt ON pt.pipeline_template_id = o.pipeline_template_id
           LEFT JOIN users u ON u.user_id = o.assigned_user_id
           WHERE o.opportunity_id = ? AND o.tenant_id = ?""",
        (opp_id, g.tenant_id),
    ).fetchone()
    if opp is None:
        abort(404)
    return opp


def _days_since(db, date_str):
    if not date_str:
        return None
    row = db.execute("SELECT CAST(julianday('now') - julianday(?) AS INTEGER) AS d", (date_str,)).fetchone()
    return row["d"]


def _risk_flags(db, opp, stage_row):
    """Computed on the fly, never persisted (see module docstring). Only
    an Active opportunity can be at risk — Nurture/Lost/Closed are settled
    states, not something to chase."""
    if opp["status"] != "Active":
        return []
    flags = []
    days_in_stage = _days_since(db, opp["stage_entered_date"])
    stage_over_window = bool(
        stage_row and stage_row["typical_window_days"] and days_in_stage is not None
        and days_in_stage > stage_row["typical_window_days"]
    )
    if stage_over_window:
        flags.append("aging")

    last_interaction = db.execute(
        "SELECT interaction_date FROM interactions WHERE opportunity_id = ? AND tenant_id = ? "
        "ORDER BY interaction_date DESC LIMIT 1",
        (opp["opportunity_id"], g.tenant_id),
    ).fetchone()
    reference_date = last_interaction["interaction_date"] if last_interaction else opp["created_at"]
    days_since_contact = _days_since(db, reference_date)
    if days_since_contact is not None and days_since_contact >= STALLED_NO_INTERACTION_DAYS:
        flags.append("stalled")

    recent = db.execute(
        "SELECT direction, outcome FROM interactions WHERE opportunity_id = ? AND tenant_id = ? "
        "ORDER BY interaction_date DESC LIMIT ?",
        (opp["opportunity_id"], g.tenant_id, GHOSTED_ATTEMPT_COUNT),
    ).fetchall()
    if len(recent) >= GHOSTED_ATTEMPT_COUNT and all(
        r["direction"] == "Outbound" and r["outcome"] in ("No Answer", "Left Voicemail") for r in recent
    ):
        flags.append("ghosted")

    incomplete_required = db.execute(
        "SELECT COUNT(*) c FROM opportunity_stage_checklist_progress WHERE opportunity_id = ? AND tenant_id = ? "
        "AND stage_number = ? AND is_required = 1 AND is_complete = 0",
        (opp["opportunity_id"], g.tenant_id, opp["current_stage_number"]),
    ).fetchone()["c"]
    if incomplete_required and stage_over_window:
        flags.append("blocked")

    return flags


def _record_stage_history(db, opportunity_id, from_status, from_stage, to_status, to_stage,
                           from_prob, to_prob, is_override, reason):
    db.execute(
        """INSERT INTO opportunity_stage_history
           (tenant_id, opportunity_id, from_status, from_stage_number, to_status, to_stage_number,
            from_probability_percent, to_probability_percent, is_manual_override, reason, changed_by_user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (g.tenant_id, opportunity_id, from_status, from_stage, to_status, to_stage,
         from_prob, to_prob, 1 if is_override else 0, reason, g.user_id),
    )


def _snapshot_checklist(db, opportunity_id, template_id, stage_number):
    """Copies the template's checklist items for this stage into this
    Opportunity's own progress rows — a snapshot, not a live join, so a
    later edit to the template doesn't retroactively alter an Opportunity's
    own history (same reasoning as the CSV-import staging tables)."""
    items = db.execute(
        "SELECT * FROM pipeline_template_checklist_items WHERE pipeline_template_id = ? AND stage_number = ? ORDER BY sort_order",
        (template_id, stage_number),
    ).fetchall()
    for item in items:
        db.execute(
            """INSERT INTO opportunity_stage_checklist_progress
               (tenant_id, opportunity_id, stage_number, item_label, is_required, sort_order)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (g.tenant_id, opportunity_id, stage_number, item["item_label"], item["is_required"], item["sort_order"]),
        )


def _generate_cadence_tasks(db, opportunity_id, template_id, stage_number, stage_entered_date, assigned_user_id):
    """Auto-generates tasks (source='Cadence') from the template's cadence
    steps for this stage, due stage_entered_date + each step's day_offset."""
    steps = db.execute(
        "SELECT * FROM pipeline_template_cadence_steps WHERE pipeline_template_id = ? AND stage_number = ? ORDER BY sort_order",
        (template_id, stage_number),
    ).fetchall()
    base_date = (stage_entered_date or "")[:10]
    for step in steps:
        due = db.execute(
            "SELECT date(?, ?) d", (base_date, f"+{step['day_offset']} days")
        ).fetchone()["d"]
        db.execute(
            """INSERT INTO tasks (tenant_id, opportunity_id, assigned_user_id, title, channel, due_date, source)
               VALUES (?, ?, ?, ?, ?, ?, 'Cadence')""",
            (g.tenant_id, opportunity_id, assigned_user_id, step["action_label"], step["channel"], due),
        )


# -------------------------------------------------------------- dashboard

@client_acquisition_bp.route("/")
@login_required
def dashboard():
    if g.role == "SystemAdmin":
        # A SystemAdmin has no tenant_id of their own (schema.sql MODULE T),
        # so this whole module -- tenant-scoped, like Organizations/Contacts
        # -- would just be empty for them. Same guard/reasoning as
        # blueprints/dashboard.py's index(); they reach master pipeline
        # templates instead via their own nav entry (client_acquisition.
        # list_templates, gated by pipeline_admin_required below).
        return redirect(url_for("client_acquisition.list_templates"))
    db = get_db()
    template_id = request.args.get("template_id", "").strip()
    templates = _templates(db)

    funnel = []
    for tpl in templates:
        if template_id and str(tpl["pipeline_template_id"]) != template_id:
            continue
        stages = db.execute(
            "SELECT * FROM pipeline_template_stages WHERE pipeline_template_id = ? ORDER BY stage_number",
            (tpl["pipeline_template_id"],),
        ).fetchall()
        stage_counts = []
        for stage in stages:
            count = db.execute(
                "SELECT COUNT(*) c FROM opportunities WHERE tenant_id = ? AND pipeline_template_id = ? "
                "AND status = 'Active' AND current_stage_number = ?",
                (g.tenant_id, tpl["pipeline_template_id"], stage["stage_number"]),
            ).fetchone()["c"]
            stage_counts.append({"stage": stage, "count": count})
        funnel.append({"template": tpl, "stages": stage_counts})

    active_opps = db.execute(
        "SELECT o.*, org.organization_name FROM opportunities o "
        "JOIN organizations org ON org.organization_id = o.organization_id "
        "WHERE o.tenant_id = ? AND o.status = 'Active'",
        (g.tenant_id,),
    ).fetchall()
    at_risk = []
    for opp in active_opps:
        stage_row = db.execute(
            "SELECT * FROM pipeline_template_stages WHERE pipeline_template_id = ? AND stage_number = ?",
            (opp["pipeline_template_id"], opp["current_stage_number"]),
        ).fetchone()
        flags = _risk_flags(db, opp, stage_row)
        if flags:
            at_risk.append({"opp": opp, "flags": flags})

    this_week_tasks = db.execute(
        """SELECT t.*, o.opportunity_name FROM tasks t
           JOIN opportunities o ON o.opportunity_id = t.opportunity_id
           WHERE t.tenant_id = ? AND t.is_complete = 0 AND t.due_date IS NOT NULL
           AND date(t.due_date) <= date('now', '+7 days')
           ORDER BY t.due_date""",
        (g.tenant_id,),
    ).fetchall()

    active_count = db.execute(
        "SELECT COUNT(*) c FROM opportunities WHERE tenant_id = ? AND status = 'Active'", (g.tenant_id,)
    ).fetchone()["c"]
    won = db.execute(
        "SELECT COUNT(*) c FROM opportunities WHERE tenant_id = ? AND status = 'Closed' AND closed_won = 1", (g.tenant_id,)
    ).fetchone()["c"]
    lost = db.execute(
        "SELECT COUNT(*) c FROM opportunities WHERE tenant_id = ? AND status = 'Lost'", (g.tenant_id,)
    ).fetchone()["c"]
    win_rate = round(100 * won / (won + lost), 1) if (won + lost) else None

    return render_template(
        "client_acquisition/dashboard.html", funnel=funnel, at_risk=at_risk, this_week_tasks=this_week_tasks,
        templates=templates, template_id=template_id, active_count=active_count, win_rate=win_rate,
    )


# ---------------------------------------------------------- opportunities

@client_acquisition_bp.route("/opportunities")
@login_required
def list_opportunities():
    db = get_db()
    status = request.args.get("status", "Active")
    template_id = request.args.get("template_id", "").strip()
    assigned_user_id = request.args.get("assigned_user_id", "").strip()
    sql = """SELECT o.*, org.organization_name, pt.template_name, u.display_name AS assigned_user_name
              FROM opportunities o
              JOIN organizations org ON org.organization_id = o.organization_id
              JOIN pipeline_templates pt ON pt.pipeline_template_id = o.pipeline_template_id
              LEFT JOIN users u ON u.user_id = o.assigned_user_id
              WHERE o.tenant_id = ?"""
    params = [g.tenant_id]
    if status and status != "All":
        sql += " AND o.status = ?"
        params.append(status)
    if template_id:
        sql += " AND o.pipeline_template_id = ?"
        params.append(template_id)
    if assigned_user_id:
        sql += " AND o.assigned_user_id = ?"
        params.append(assigned_user_id)
    sql += " ORDER BY o.updated_at DESC"
    opps = db.execute(sql, params).fetchall()
    return render_template(
        "client_acquisition/opportunity_list.html", opps=opps, status=status,
        template_id=template_id, assigned_user_id=assigned_user_id,
        templates=_templates(db), users=_tenant_users(db),
    )


@client_acquisition_bp.route("/opportunities/new", methods=["GET", "POST"])
@login_required
def new_opportunity():
    db = get_db()
    if request.method == "POST":
        form = request.form
        organization_id = form.get("organization_id") or None
        pipeline_template_id = form.get("pipeline_template_id") or None
        name = form.get("opportunity_name", "").strip()
        errors = []
        if not organization_id:
            errors.append("Choose an Organization.")
        if not pipeline_template_id:
            errors.append("Choose a Pipeline Template.")
        if not name:
            errors.append("Opportunity name is required.")
        if errors:
            for e in errors:
                flash(e, "error")
            return render_template(
                "client_acquisition/opportunity_form.html", opp=None,
                organizations=_organizations(db), templates=_templates(db), users=_tenant_users(db),
            )
        first_stage = db.execute(
            "SELECT * FROM pipeline_template_stages WHERE pipeline_template_id = ? ORDER BY stage_number LIMIT 1",
            (pipeline_template_id,),
        ).fetchone()
        cur = db.execute(
            """INSERT INTO opportunities
               (tenant_id, organization_id, pipeline_template_id, opportunity_name, assigned_user_id,
                current_stage_number, probability_percent, opportunity_value, lead_source, lead_source_detail)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                g.tenant_id, organization_id, pipeline_template_id, name, form.get("assigned_user_id") or None,
                first_stage["stage_number"] if first_stage else 1,
                first_stage["probability_percent"] if first_stage else 0,
                _float_or_none(form.get("opportunity_value")),
                form.get("lead_source", "").strip() or None,
                form.get("lead_source_detail", "").strip() or None,
            ),
        )
        opp_id = cur.lastrowid
        db.commit()
        if first_stage:
            _record_stage_history(
                db, opp_id, None, None, "Active", first_stage["stage_number"],
                None, first_stage["probability_percent"], False, None,
            )
            _snapshot_checklist(db, opp_id, pipeline_template_id, first_stage["stage_number"])
            _generate_cadence_tasks(
                db, opp_id, pipeline_template_id, first_stage["stage_number"], _now(db), form.get("assigned_user_id") or None
            )
            db.commit()
        log_action("Create", "opportunity", opp_id, f"Created opportunity '{name}'")
        flash("Opportunity created.", "success")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    return render_template(
        "client_acquisition/opportunity_form.html", opp=None,
        organizations=_organizations(db), templates=_templates(db), users=_tenant_users(db),
    )


@client_acquisition_bp.route("/opportunities/<int:opp_id>")
@login_required
def view_opportunity(opp_id):
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    stages = db.execute(
        "SELECT * FROM pipeline_template_stages WHERE pipeline_template_id = ? ORDER BY stage_number",
        (opp["pipeline_template_id"],),
    ).fetchall()
    stage_row = next((s for s in stages if s["stage_number"] == opp["current_stage_number"]), None)
    next_stage = next((s for s in stages if s["stage_number"] == opp["current_stage_number"] + 1), None)
    checklist = db.execute(
        "SELECT * FROM opportunity_stage_checklist_progress WHERE opportunity_id = ? AND tenant_id = ? AND stage_number = ? "
        "ORDER BY sort_order",
        (opp_id, g.tenant_id, opp["current_stage_number"]),
    ).fetchall()
    incomplete_required = sum(1 for c in checklist if c["is_required"] and not c["is_complete"])
    contacts = db.execute(
        """SELECT oc.*, c.full_name FROM opportunity_contacts oc
           JOIN contacts c ON c.contact_id = oc.contact_id
           WHERE oc.opportunity_id = ? AND oc.tenant_id = ? ORDER BY c.full_name""",
        (opp_id, g.tenant_id),
    ).fetchall()
    linked_contact_ids = {c["contact_id"] for c in contacts}
    org_contacts = [
        c for c in db.execute(
            "SELECT contact_id, full_name FROM contacts WHERE current_organization_id = ? AND tenant_id = ? "
            "AND is_deleted = 0 ORDER BY full_name",
            (opp["organization_id"], g.tenant_id),
        ).fetchall()
        if c["contact_id"] not in linked_contact_ids
    ]
    interactions = db.execute(
        """SELECT i.*, c.full_name AS contact_name, u.display_name AS created_by_name
           FROM interactions i
           LEFT JOIN contacts c ON c.contact_id = i.contact_id
           LEFT JOIN users u ON u.user_id = i.created_by_user_id
           WHERE i.opportunity_id = ? AND i.tenant_id = ? ORDER BY i.interaction_date DESC""",
        (opp_id, g.tenant_id),
    ).fetchall()
    tasks = db.execute(
        """SELECT t.*, u.display_name AS assigned_user_name FROM tasks t
           LEFT JOIN users u ON u.user_id = t.assigned_user_id
           WHERE t.opportunity_id = ? AND t.tenant_id = ? ORDER BY t.is_complete, t.due_date""",
        (opp_id, g.tenant_id),
    ).fetchall()
    history = db.execute(
        """SELECT h.*, u.display_name AS changed_by_name FROM opportunity_stage_history h
           LEFT JOIN users u ON u.user_id = h.changed_by_user_id
           WHERE h.opportunity_id = ? AND h.tenant_id = ? ORDER BY h.changed_at DESC""",
        (opp_id, g.tenant_id),
    ).fetchall()
    flags = _risk_flags(db, opp, stage_row)

    return render_template(
        "client_acquisition/opportunity_view.html", opp=opp, stages=stages, stage_row=stage_row,
        next_stage=next_stage, checklist=checklist, incomplete_required=incomplete_required,
        contacts=contacts, org_contacts=org_contacts, interactions=interactions, tasks=tasks,
        history=history, flags=flags, contact_roles=CONTACT_ROLES, channels=CHANNELS,
        directions=DIRECTIONS, outcomes=OUTCOMES, users=_tenant_users(db),
    )


@client_acquisition_bp.route("/opportunities/<int:opp_id>/edit", methods=["GET", "POST"])
@login_required
def edit_opportunity(opp_id):
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    if request.method == "POST":
        form = request.form
        name = form.get("opportunity_name", "").strip()
        if not name:
            flash("Opportunity name is required.", "error")
            return redirect(url_for("client_acquisition.edit_opportunity", opp_id=opp_id))
        db.execute(
            """UPDATE opportunities SET opportunity_name = ?, assigned_user_id = ?, opportunity_value = ?,
               lead_source = ?, lead_source_detail = ?, next_action = ?, next_action_date = ?, updated_at = datetime('now')
               WHERE opportunity_id = ? AND tenant_id = ?""",
            (
                name, form.get("assigned_user_id") or None, _float_or_none(form.get("opportunity_value")),
                form.get("lead_source", "").strip() or None, form.get("lead_source_detail", "").strip() or None,
                form.get("next_action", "").strip() or None, form.get("next_action_date") or None,
                opp_id, g.tenant_id,
            ),
        )
        db.commit()
        log_action("Update", "opportunity", opp_id, f"Updated opportunity '{name}'")
        flash("Opportunity updated.", "success")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    return render_template(
        "client_acquisition/opportunity_form.html", opp=opp,
        organizations=_organizations(db), templates=_templates(db), users=_tenant_users(db),
    )


@client_acquisition_bp.route("/opportunities/<int:opp_id>/checklist/<int:progress_id>/toggle", methods=["POST"])
@login_required
def toggle_checklist_item(opp_id, progress_id):
    db = get_db()
    _get_opportunity(db, opp_id)
    item = db.execute(
        "SELECT * FROM opportunity_stage_checklist_progress WHERE progress_id = ? AND opportunity_id = ? AND tenant_id = ?",
        (progress_id, opp_id, g.tenant_id),
    ).fetchone()
    if item is None:
        abort(404)
    new_state = 0 if item["is_complete"] else 1
    db.execute(
        "UPDATE opportunity_stage_checklist_progress SET is_complete = ?, completed_at = ?, completed_by_user_id = ? "
        "WHERE progress_id = ? AND tenant_id = ?",
        (new_state, _now(db) if new_state else None, g.user_id if new_state else None, progress_id, g.tenant_id),
    )
    db.commit()
    return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))


# --------------------------------------------------------- stage movement

@client_acquisition_bp.route("/opportunities/<int:opp_id>/advance", methods=["POST"])
@login_required
def advance_stage(opp_id):
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    if opp["status"] != "Active":
        flash("Only an Active opportunity can advance stages.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    stages = db.execute(
        "SELECT * FROM pipeline_template_stages WHERE pipeline_template_id = ? ORDER BY stage_number",
        (opp["pipeline_template_id"],),
    ).fetchall()
    current_stage_number = opp["current_stage_number"]
    next_stage = next((s for s in stages if s["stage_number"] == current_stage_number + 1), None)
    if next_stage is None:
        flash("This is already the final stage of its pipeline template — use Close to mark it Won.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))

    incomplete_required = db.execute(
        "SELECT COUNT(*) c FROM opportunity_stage_checklist_progress WHERE opportunity_id = ? AND tenant_id = ? "
        "AND stage_number = ? AND is_required = 1 AND is_complete = 0",
        (opp_id, g.tenant_id, current_stage_number),
    ).fetchone()["c"]
    reason = request.form.get("reason", "").strip()
    override = bool(request.form.get("override"))
    if incomplete_required and not override:
        flash(
            f"{incomplete_required} required checklist item(s) for this stage aren't complete yet. "
            f"Check them off, or advance anyway with an override reason.", "error",
        )
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    if incomplete_required and override and not reason:
        flash("A reason is required to advance past an incomplete checklist.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))

    now = _now(db)
    db.execute(
        "UPDATE opportunities SET current_stage_number = ?, stage_entered_date = ?, probability_percent = ?, "
        "updated_at = datetime('now') WHERE opportunity_id = ? AND tenant_id = ?",
        (next_stage["stage_number"], now, next_stage["probability_percent"], opp_id, g.tenant_id),
    )
    _record_stage_history(
        db, opp_id, opp["status"], current_stage_number, opp["status"], next_stage["stage_number"],
        opp["probability_percent"], next_stage["probability_percent"], bool(incomplete_required and override), reason or None,
    )
    _snapshot_checklist(db, opp_id, opp["pipeline_template_id"], next_stage["stage_number"])
    _generate_cadence_tasks(db, opp_id, opp["pipeline_template_id"], next_stage["stage_number"], now, opp["assigned_user_id"])
    db.commit()
    log_action(
        "Update", "opportunity", opp_id,
        f"Advanced '{opp['opportunity_name']}' to stage {next_stage['stage_number']} ({next_stage['stage_name']})",
    )
    flash(f"Advanced to {next_stage['stage_name']}.", "success")
    return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))


@client_acquisition_bp.route("/opportunities/<int:opp_id>/revert", methods=["POST"])
@login_required
def revert_stage(opp_id):
    """Manual override to move an Opportunity back a stage — rare, but
    needed when something falls through (e.g. a deal thought to be at
    Proposal turns out to still need Discovery). Always requires a reason,
    unlike advance_stage where a reason is only required to bypass an
    incomplete checklist."""
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    if opp["status"] != "Active":
        flash("Only an Active opportunity can move stages.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("A reason is required to move an opportunity backward.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    current_stage_number = opp["current_stage_number"]
    if current_stage_number <= 1:
        flash("This is already the first stage.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    prev_stage = db.execute(
        "SELECT * FROM pipeline_template_stages WHERE pipeline_template_id = ? AND stage_number = ?",
        (opp["pipeline_template_id"], current_stage_number - 1),
    ).fetchone()
    if prev_stage is None:
        abort(404)
    now = _now(db)
    db.execute(
        "UPDATE opportunities SET current_stage_number = ?, stage_entered_date = ?, probability_percent = ?, "
        "updated_at = datetime('now') WHERE opportunity_id = ? AND tenant_id = ?",
        (prev_stage["stage_number"], now, prev_stage["probability_percent"], opp_id, g.tenant_id),
    )
    _record_stage_history(
        db, opp_id, opp["status"], current_stage_number, opp["status"], prev_stage["stage_number"],
        opp["probability_percent"], prev_stage["probability_percent"], True, reason,
    )
    # Re-snapshot the checklist for the stage we're moving back into — its
    # own progress from the first time through is history now, tracked in
    # opportunity_stage_history, not resurrected here.
    _snapshot_checklist(db, opp_id, opp["pipeline_template_id"], prev_stage["stage_number"])
    db.commit()
    log_action(
        "Update", "opportunity", opp_id,
        f"Moved '{opp['opportunity_name']}' back to stage {prev_stage['stage_number']} ({prev_stage['stage_name']}): {reason}",
    )
    flash(f"Moved back to {prev_stage['stage_name']}.", "success")
    return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))


# ---------------------------------------------------------- side states

@client_acquisition_bp.route("/opportunities/<int:opp_id>/nurture", methods=["GET", "POST"])
@login_required
def nurture_opportunity(opp_id):
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    if request.method == "POST":
        form = request.form
        reason = form.get("nurture_reason") or None
        if reason not in NURTURE_REASONS:
            flash("Choose a nurture reason.", "error")
            return redirect(url_for("client_acquisition.nurture_opportunity", opp_id=opp_id))
        revisit_date = form.get("nurture_revisit_date") or None
        db.execute(
            "UPDATE opportunities SET status = 'Nurture', nurture_reason = ?, nurture_revisit_date = ?, "
            "updated_at = datetime('now') WHERE opportunity_id = ? AND tenant_id = ?",
            (reason, revisit_date, opp_id, g.tenant_id),
        )
        _record_stage_history(
            db, opp_id, opp["status"], opp["current_stage_number"], "Nurture", opp["current_stage_number"],
            opp["probability_percent"], opp["probability_percent"], False, reason,
        )
        if revisit_date:
            db.execute(
                "INSERT INTO tasks (tenant_id, opportunity_id, assigned_user_id, title, due_date, source) "
                "VALUES (?, ?, ?, ?, ?, 'Nurture Revisit')",
                (g.tenant_id, opp_id, opp["assigned_user_id"], f"Revisit: {opp['opportunity_name']}", revisit_date),
            )
        db.commit()
        log_action("Update", "opportunity", opp_id, f"Moved '{opp['opportunity_name']}' to Nurture ({reason})")
        flash("Moved to Nurture.", "success")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    return render_template("client_acquisition/nurture_form.html", opp=opp, nurture_reasons=NURTURE_REASONS)


@client_acquisition_bp.route("/opportunities/<int:opp_id>/reactivate", methods=["POST"])
@login_required
def reactivate_opportunity(opp_id):
    """Re-entry from Nurture or Lost, at whatever stage the Opportunity was
    already on — per the project doc's decision that Nurture can re-enter
    at any stage rather than always restarting at stage 1."""
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    if opp["status"] not in ("Nurture", "Lost"):
        flash("Only a Nurture or Lost opportunity can be reactivated.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    db.execute(
        "UPDATE opportunities SET status = 'Active', nurture_reason = NULL, nurture_revisit_date = NULL, "
        "lost_reason = NULL, lost_date = NULL, stage_entered_date = datetime('now'), updated_at = datetime('now') "
        "WHERE opportunity_id = ? AND tenant_id = ?",
        (opp_id, g.tenant_id),
    )
    _record_stage_history(
        db, opp_id, opp["status"], opp["current_stage_number"], "Active", opp["current_stage_number"],
        opp["probability_percent"], opp["probability_percent"], False, "Reactivated",
    )
    db.commit()
    log_action("Update", "opportunity", opp_id, f"Reactivated '{opp['opportunity_name']}' at stage {opp['current_stage_number']}")
    flash("Reactivated.", "success")
    return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))


@client_acquisition_bp.route("/opportunities/<int:opp_id>/lost", methods=["GET", "POST"])
@login_required
def lose_opportunity(opp_id):
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    if request.method == "POST":
        reason = request.form.get("lost_reason") or None
        if reason not in LOST_REASONS:
            flash("Choose a lost reason.", "error")
            return redirect(url_for("client_acquisition.lose_opportunity", opp_id=opp_id))
        db.execute(
            "UPDATE opportunities SET status = 'Lost', lost_reason = ?, lost_date = date('now'), updated_at = datetime('now') "
            "WHERE opportunity_id = ? AND tenant_id = ?",
            (reason, opp_id, g.tenant_id),
        )
        _record_stage_history(
            db, opp_id, opp["status"], opp["current_stage_number"], "Lost", opp["current_stage_number"],
            opp["probability_percent"], 0, False, reason,
        )
        db.commit()
        log_action("Update", "opportunity", opp_id, f"Marked '{opp['opportunity_name']}' Lost ({reason})")
        flash("Marked as Lost.", "success")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    return render_template("client_acquisition/lost_form.html", opp=opp, lost_reasons=LOST_REASONS)


@client_acquisition_bp.route("/opportunities/<int:opp_id>/close", methods=["POST"])
@login_required
def close_opportunity(opp_id):
    """Closed always means Won here — the Lost side-state already covers a
    terminal loss with its own reason, so this is the module's one "the
    client was acquired" action. Handoff to Customer Service is a stub note
    only; that module isn't built yet (blueprints/customer_service.py)."""
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    if opp["status"] not in ("Active", "Nurture"):
        flash("Only an Active or Nurture opportunity can be closed.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    db.execute(
        "UPDATE opportunities SET status = 'Closed', closed_won = 1, closed_date = date('now'), "
        "probability_percent = 100, updated_at = datetime('now') WHERE opportunity_id = ? AND tenant_id = ?",
        (opp_id, g.tenant_id),
    )
    _record_stage_history(
        db, opp_id, opp["status"], opp["current_stage_number"], "Closed", opp["current_stage_number"],
        opp["probability_percent"], 100, False, "Won",
    )
    db.commit()
    log_action("Update", "opportunity", opp_id, f"Closed '{opp['opportunity_name']}' as Won")
    flash(
        f"'{opp['opportunity_name']}' closed as Won! Once Customer Service is built, this is where the "
        f"handoff to the delivery team will happen.", "success",
    )
    return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))


# --------------------------------------------------------- opportunity contacts

@client_acquisition_bp.route("/opportunities/<int:opp_id>/contacts/add", methods=["POST"])
@login_required
def add_opportunity_contact(opp_id):
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    contact_id = request.form.get("contact_id") or None
    role = request.form.get("contact_role") or None
    if role and role not in CONTACT_ROLES:
        role = None
    if not contact_id:
        flash("Choose a contact to add.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    contact = db.execute(
        "SELECT full_name FROM contacts WHERE contact_id = ? AND tenant_id = ?", (contact_id, g.tenant_id)
    ).fetchone()
    if contact is None:
        abort(404)
    existing = db.execute(
        "SELECT 1 FROM opportunity_contacts WHERE opportunity_id = ? AND contact_id = ? AND tenant_id = ?",
        (opp_id, contact_id, g.tenant_id),
    ).fetchone()
    if existing:
        flash(f"{contact['full_name']} is already on this opportunity.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    db.execute(
        "INSERT INTO opportunity_contacts (tenant_id, opportunity_id, contact_id, contact_role) VALUES (?, ?, ?, ?)",
        (g.tenant_id, opp_id, contact_id, role),
    )
    db.commit()
    log_action("Create", "opportunity_contact", opp_id, f"Added {contact['full_name']} to '{opp['opportunity_name']}'")
    flash(f"{contact['full_name']} added.", "success")
    return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))


@client_acquisition_bp.route("/opportunities/<int:opp_id>/contacts/<int:contact_id>/remove", methods=["POST"])
@login_required
def remove_opportunity_contact(opp_id, contact_id):
    db = get_db()
    _get_opportunity(db, opp_id)
    db.execute(
        "DELETE FROM opportunity_contacts WHERE opportunity_id = ? AND contact_id = ? AND tenant_id = ?",
        (opp_id, contact_id, g.tenant_id),
    )
    db.commit()
    log_action("Delete", "opportunity_contact", opp_id, f"Removed contact #{contact_id}")
    flash("Contact removed from this opportunity.", "success")
    return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))


# ------------------------------------------------------------- interactions

@client_acquisition_bp.route("/opportunities/<int:opp_id>/interactions/new", methods=["POST"])
@login_required
def new_interaction(opp_id):
    db = get_db()
    opp = _get_opportunity(db, opp_id)
    form = request.form
    channel = form.get("channel") or ""
    direction = form.get("direction") or ""
    outcome = form.get("outcome") or None
    if channel not in CHANNELS or direction not in DIRECTIONS:
        flash("Choose a valid channel and direction.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    if outcome and outcome not in OUTCOMES:
        outcome = None
    contact_id = form.get("contact_id") or None
    db.execute(
        """INSERT INTO interactions
           (tenant_id, opportunity_id, contact_id, channel, direction, summary, material_shared, outcome, created_by_user_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            g.tenant_id, opp_id, contact_id, channel, direction,
            form.get("summary", "").strip() or None, form.get("material_shared", "").strip() or None,
            outcome, g.user_id,
        ),
    )
    next_action = form.get("next_action", "").strip()
    next_action_date = form.get("next_action_date", "").strip()
    if next_action or next_action_date:
        db.execute(
            "UPDATE opportunities SET next_action = ?, next_action_date = ?, updated_at = datetime('now') "
            "WHERE opportunity_id = ? AND tenant_id = ?",
            (next_action or None, next_action_date or None, opp_id, g.tenant_id),
        )
    db.commit()
    log_action("Create", "interaction", opp_id, f"Logged {channel} interaction on '{opp['opportunity_name']}'")
    flash("Interaction logged.", "success")
    return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))


# -------------------------------------------------------------------- tasks

@client_acquisition_bp.route("/opportunities/<int:opp_id>/tasks/new", methods=["POST"])
@login_required
def new_task(opp_id):
    db = get_db()
    _get_opportunity(db, opp_id)
    form = request.form
    title = form.get("title", "").strip()
    if not title:
        flash("Task title is required.", "error")
        return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))
    channel = form.get("channel") or None
    if channel and channel not in CHANNELS:
        channel = None
    db.execute(
        "INSERT INTO tasks (tenant_id, opportunity_id, assigned_user_id, title, channel, due_date, source) "
        "VALUES (?, ?, ?, ?, ?, ?, 'Manual')",
        (g.tenant_id, opp_id, form.get("assigned_user_id") or None, title, channel, form.get("due_date") or None),
    )
    db.commit()
    log_action("Create", "task", opp_id, f"Added task '{title}'")
    flash("Task added.", "success")
    return redirect(url_for("client_acquisition.view_opportunity", opp_id=opp_id))


@client_acquisition_bp.route("/tasks/<int:task_id>/complete", methods=["POST"])
@login_required
def complete_task(task_id):
    db = get_db()
    task = db.execute("SELECT * FROM tasks WHERE task_id = ? AND tenant_id = ?", (task_id, g.tenant_id)).fetchone()
    if task is None:
        abort(404)
    db.execute(
        "UPDATE tasks SET is_complete = 1, completed_at = datetime('now') WHERE task_id = ? AND tenant_id = ?",
        (task_id, g.tenant_id),
    )
    db.commit()
    flash("Task marked complete.", "success")
    return redirect(request.referrer or url_for("client_acquisition.dashboard"))


# ---------------------------------------------------------------- reporting

@client_acquisition_bp.route("/reporting")
@login_required
def reporting():
    db = get_db()
    won = db.execute(
        "SELECT COUNT(*) c FROM opportunities WHERE tenant_id = ? AND status = 'Closed' AND closed_won = 1", (g.tenant_id,)
    ).fetchone()["c"]
    lost = db.execute(
        "SELECT COUNT(*) c FROM opportunities WHERE tenant_id = ? AND status = 'Lost'", (g.tenant_id,)
    ).fetchone()["c"]
    win_rate = round(100 * won / (won + lost), 1) if (won + lost) else None
    loss_reasons = db.execute(
        "SELECT lost_reason, COUNT(*) c FROM opportunities WHERE tenant_id = ? AND status = 'Lost' "
        "GROUP BY lost_reason ORDER BY c DESC",
        (g.tenant_id,),
    ).fetchall()
    by_rep = db.execute(
        """SELECT u.display_name,
                  SUM(CASE WHEN o.status = 'Closed' AND o.closed_won = 1 THEN 1 ELSE 0 END) AS won,
                  SUM(CASE WHEN o.status = 'Lost' THEN 1 ELSE 0 END) AS lost
           FROM opportunities o LEFT JOIN users u ON u.user_id = o.assigned_user_id
           WHERE o.tenant_id = ? GROUP BY o.assigned_user_id ORDER BY won DESC""",
        (g.tenant_id,),
    ).fetchall()
    avg_cycle_days = db.execute(
        "SELECT AVG(julianday(closed_date) - julianday(created_at)) AS d FROM opportunities "
        "WHERE tenant_id = ? AND status = 'Closed' AND closed_won = 1 AND closed_date IS NOT NULL",
        (g.tenant_id,),
    ).fetchone()["d"]
    # material_effectiveness (which shared material correlates with wins) is
    # explicitly deferred -- interactions.material_shared is free text today
    # with nothing structured enough yet to aggregate meaningfully.
    return render_template(
        "client_acquisition/reporting.html", won=won, lost=lost, win_rate=win_rate,
        loss_reasons=loss_reasons, by_rep=by_rep,
        avg_cycle_days=round(avg_cycle_days, 1) if avg_cycle_days is not None else None,
    )


# -------------------------------------------------- pipeline template admin
#
# Tenant-scoped CRUD for a tenant's own (cloned) pipeline templates, also
# reachable by a SystemAdmin to edit the GSS_PLATFORM tenant's master
# templates -- "GSS Platform" is itself just a row in tenants (see db.py's
# _migration_create_platform_tenant), so the same view functions serve both
# audiences; pipeline_admin_required below decides which tenant_id a given
# request operates on (g.pipeline_tenant_id) instead of assuming g.tenant_id.

def pipeline_admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        token = session.get("auth_token")
        if not token:
            session.clear()
            return redirect(url_for("auth_bp.login"))
        role = session.get("role")
        g.role = role
        g.user_id = session.get("user_id")
        g.username = session.get("username")
        g.display_name = session.get("display_name")
        if role == "SystemAdmin":
            db = get_db()
            platform = db.execute("SELECT tenant_id FROM tenants WHERE tenant_code = 'GSS_PLATFORM'").fetchone()
            if not platform:
                abort(404)
            g.pipeline_tenant_id = platform["tenant_id"]
            g.tenant_name = "GSS Platform (master templates)"
        elif role == "TenantAdmin":
            g.dek = get_current_dek()
            g.tenant_id = session.get("tenant_id")
            g.tenant_name = session.get("tenant_name")
            g.pipeline_tenant_id = g.tenant_id
        else:
            flash("That page is restricted to Tenant Admins.", "error")
            abort(403)
        if session.get("must_change_password") and request.endpoint != "system_mgmt.change_password":
            flash("Please choose a new password to continue.", "error")
            return redirect(url_for("system_mgmt.change_password"))
        return view(*args, **kwargs)
    return wrapped


def _get_template(db, template_id):
    tpl = db.execute(
        "SELECT * FROM pipeline_templates WHERE pipeline_template_id = ? AND tenant_id = ?",
        (template_id, g.pipeline_tenant_id),
    ).fetchone()
    if tpl is None:
        abort(404)
    return tpl


@client_acquisition_bp.route("/templates")
@pipeline_admin_required
def list_templates():
    db = get_db()
    templates = db.execute(
        """SELECT t.*, (SELECT COUNT(*) FROM pipeline_template_stages s WHERE s.pipeline_template_id = t.pipeline_template_id) AS stage_count
           FROM pipeline_templates t WHERE t.tenant_id = ? ORDER BY t.sort_order, t.template_name COLLATE NOCASE""",
        (g.pipeline_tenant_id,),
    ).fetchall()
    return render_template("client_acquisition/templates_list.html", templates=templates)


@client_acquisition_bp.route("/templates/new", methods=["GET", "POST"])
@pipeline_admin_required
def new_template():
    db = get_db()
    if request.method == "POST":
        form = request.form
        name = form.get("template_name", "").strip()
        if not name:
            flash("Template name is required.", "error")
            return render_template("client_acquisition/template_form.html", tpl=None)
        cur = db.execute(
            "INSERT INTO pipeline_templates (tenant_id, template_name, win_criteria_prompt, disqualify_after_days) "
            "VALUES (?, ?, ?, ?)",
            (g.pipeline_tenant_id, name, form.get("win_criteria_prompt", "").strip() or None,
             _int_or_none(form.get("disqualify_after_days"))),
        )
        db.commit()
        template_id = cur.lastrowid
        log_action("Create", "pipeline_template", template_id, f"Created pipeline template '{name}'")
        flash("Template created — add its stages next.", "success")
        return redirect(url_for("client_acquisition.edit_template", template_id=template_id))
    return render_template("client_acquisition/template_form.html", tpl=None)


@client_acquisition_bp.route("/templates/<int:template_id>/edit", methods=["GET", "POST"])
@pipeline_admin_required
def edit_template(template_id):
    db = get_db()
    tpl = _get_template(db, template_id)
    if request.method == "POST":
        form = request.form
        name = form.get("template_name", "").strip()
        if not name:
            flash("Template name is required.", "error")
            return redirect(url_for("client_acquisition.edit_template", template_id=template_id))
        db.execute(
            "UPDATE pipeline_templates SET template_name = ?, win_criteria_prompt = ?, disqualify_after_days = ?, "
            "is_active = ?, updated_at = datetime('now') WHERE pipeline_template_id = ? AND tenant_id = ?",
            (
                name, form.get("win_criteria_prompt", "").strip() or None, _int_or_none(form.get("disqualify_after_days")),
                1 if form.get("is_active") else 0, template_id, g.pipeline_tenant_id,
            ),
        )
        db.commit()
        log_action("Update", "pipeline_template", template_id, f"Updated pipeline template '{name}'")
        flash("Template updated.", "success")
        return redirect(url_for("client_acquisition.edit_template", template_id=template_id))

    stages = db.execute(
        "SELECT * FROM pipeline_template_stages WHERE pipeline_template_id = ? ORDER BY stage_number",
        (template_id,),
    ).fetchall()
    checklist_by_stage, cadence_by_stage = {}, {}
    for stage in stages:
        checklist_by_stage[stage["stage_number"]] = db.execute(
            "SELECT * FROM pipeline_template_checklist_items WHERE pipeline_template_id = ? AND stage_number = ? ORDER BY sort_order",
            (template_id, stage["stage_number"]),
        ).fetchall()
        cadence_by_stage[stage["stage_number"]] = db.execute(
            "SELECT * FROM pipeline_template_cadence_steps WHERE pipeline_template_id = ? AND stage_number = ? ORDER BY sort_order",
            (template_id, stage["stage_number"]),
        ).fetchall()
    in_use = db.execute(
        "SELECT COUNT(*) c FROM opportunities WHERE pipeline_template_id = ? AND tenant_id = ?",
        (template_id, g.pipeline_tenant_id),
    ).fetchone()["c"]
    return render_template(
        "client_acquisition/template_edit.html", tpl=tpl, stages=stages,
        checklist_by_stage=checklist_by_stage, cadence_by_stage=cadence_by_stage,
        in_use=in_use, channels=CHANNELS,
    )


@client_acquisition_bp.route("/templates/<int:template_id>/delete", methods=["POST"])
@pipeline_admin_required
def delete_template(template_id):
    db = get_db()
    tpl = _get_template(db, template_id)
    in_use = db.execute(
        "SELECT COUNT(*) c FROM opportunities WHERE pipeline_template_id = ? AND tenant_id = ?",
        (template_id, g.pipeline_tenant_id),
    ).fetchone()["c"]
    if in_use:
        flash(
            f"'{tpl['template_name']}' is used by {in_use} opportunity(ies) and can't be deleted — deactivate it instead.",
            "error",
        )
        return redirect(url_for("client_acquisition.edit_template", template_id=template_id))
    db.execute("DELETE FROM pipeline_template_cadence_steps WHERE pipeline_template_id = ? AND tenant_id = ?", (template_id, g.pipeline_tenant_id))
    db.execute("DELETE FROM pipeline_template_checklist_items WHERE pipeline_template_id = ? AND tenant_id = ?", (template_id, g.pipeline_tenant_id))
    db.execute("DELETE FROM pipeline_template_stages WHERE pipeline_template_id = ? AND tenant_id = ?", (template_id, g.pipeline_tenant_id))
    db.execute("DELETE FROM pipeline_templates WHERE pipeline_template_id = ? AND tenant_id = ?", (template_id, g.pipeline_tenant_id))
    db.commit()
    log_action("Delete", "pipeline_template", template_id, f"Deleted unused pipeline template '{tpl['template_name']}'")
    flash(f"'{tpl['template_name']}' deleted.", "success")
    return redirect(url_for("client_acquisition.list_templates"))


@client_acquisition_bp.route("/templates/<int:template_id>/stages/new", methods=["POST"])
@pipeline_admin_required
def new_stage(template_id):
    db = get_db()
    _get_template(db, template_id)
    form = request.form
    stage_name = form.get("stage_name", "").strip()
    if not stage_name:
        flash("Stage name is required.", "error")
        return redirect(url_for("client_acquisition.edit_template", template_id=template_id))
    next_num = db.execute(
        "SELECT COALESCE(MAX(stage_number), 0) + 1 AS n FROM pipeline_template_stages WHERE pipeline_template_id = ?",
        (template_id,),
    ).fetchone()["n"]
    db.execute(
        "INSERT INTO pipeline_template_stages (tenant_id, pipeline_template_id, stage_number, stage_name, "
        "typical_window_days, probability_percent) VALUES (?, ?, ?, ?, ?, ?)",
        (
            g.pipeline_tenant_id, template_id, next_num, stage_name,
            _int_or_none(form.get("typical_window_days")), _int_or_none(form.get("probability_percent")) or 0,
        ),
    )
    db.commit()
    flash(f"Stage {next_num} added.", "success")
    return redirect(url_for("client_acquisition.edit_template", template_id=template_id))


@client_acquisition_bp.route("/templates/<int:template_id>/stages/<int:stage_number>/delete", methods=["POST"])
@pipeline_admin_required
def delete_stage(template_id, stage_number):
    db = get_db()
    _get_template(db, template_id)
    in_use = db.execute(
        "SELECT COUNT(*) c FROM opportunities WHERE pipeline_template_id = ? AND tenant_id = ? AND current_stage_number = ?",
        (template_id, g.pipeline_tenant_id, stage_number),
    ).fetchone()["c"]
    if in_use:
        flash(f"{in_use} opportunity(ies) are currently on this stage — move them first.", "error")
        return redirect(url_for("client_acquisition.edit_template", template_id=template_id))
    db.execute("DELETE FROM pipeline_template_cadence_steps WHERE pipeline_template_id = ? AND stage_number = ? AND tenant_id = ?", (template_id, stage_number, g.pipeline_tenant_id))
    db.execute("DELETE FROM pipeline_template_checklist_items WHERE pipeline_template_id = ? AND stage_number = ? AND tenant_id = ?", (template_id, stage_number, g.pipeline_tenant_id))
    db.execute("DELETE FROM pipeline_template_stages WHERE pipeline_template_id = ? AND stage_number = ? AND tenant_id = ?", (template_id, stage_number, g.pipeline_tenant_id))
    db.commit()
    flash(f"Stage {stage_number} deleted.", "success")
    return redirect(url_for("client_acquisition.edit_template", template_id=template_id))


@client_acquisition_bp.route("/templates/<int:template_id>/stages/<int:stage_number>/checklist/new", methods=["POST"])
@pipeline_admin_required
def new_checklist_item(template_id, stage_number):
    db = get_db()
    _get_template(db, template_id)
    label = request.form.get("item_label", "").strip()
    if not label:
        flash("Checklist item text is required.", "error")
        return redirect(url_for("client_acquisition.edit_template", template_id=template_id))
    next_sort = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM pipeline_template_checklist_items "
        "WHERE pipeline_template_id = ? AND stage_number = ?",
        (template_id, stage_number),
    ).fetchone()["n"]
    db.execute(
        "INSERT INTO pipeline_template_checklist_items (tenant_id, pipeline_template_id, stage_number, item_label, is_required, sort_order) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (g.pipeline_tenant_id, template_id, stage_number, label, 1 if request.form.get("is_required") else 0, next_sort),
    )
    db.commit()
    flash("Checklist item added.", "success")
    return redirect(url_for("client_acquisition.edit_template", template_id=template_id))


@client_acquisition_bp.route("/templates/<int:template_id>/checklist/<int:checklist_item_id>/delete", methods=["POST"])
@pipeline_admin_required
def delete_checklist_item(template_id, checklist_item_id):
    db = get_db()
    _get_template(db, template_id)
    db.execute(
        "DELETE FROM pipeline_template_checklist_items WHERE checklist_item_id = ? AND pipeline_template_id = ? AND tenant_id = ?",
        (checklist_item_id, template_id, g.pipeline_tenant_id),
    )
    db.commit()
    flash("Checklist item deleted.", "success")
    return redirect(url_for("client_acquisition.edit_template", template_id=template_id))


@client_acquisition_bp.route("/templates/<int:template_id>/stages/<int:stage_number>/cadence/new", methods=["POST"])
@pipeline_admin_required
def new_cadence_step(template_id, stage_number):
    db = get_db()
    _get_template(db, template_id)
    form = request.form
    action_label = form.get("action_label", "").strip()
    if not action_label:
        flash("Cadence action text is required.", "error")
        return redirect(url_for("client_acquisition.edit_template", template_id=template_id))
    channel = form.get("channel") or None
    if channel and channel not in CHANNELS:
        channel = None
    next_sort = db.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 AS n FROM pipeline_template_cadence_steps "
        "WHERE pipeline_template_id = ? AND stage_number = ?",
        (template_id, stage_number),
    ).fetchone()["n"]
    db.execute(
        "INSERT INTO pipeline_template_cadence_steps (tenant_id, pipeline_template_id, stage_number, day_offset, action_label, channel, sort_order) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (g.pipeline_tenant_id, template_id, stage_number, _int_or_none(form.get("day_offset")) or 0, action_label, channel, next_sort),
    )
    db.commit()
    flash("Cadence step added.", "success")
    return redirect(url_for("client_acquisition.edit_template", template_id=template_id))


@client_acquisition_bp.route("/templates/<int:template_id>/cadence/<int:cadence_step_id>/delete", methods=["POST"])
@pipeline_admin_required
def delete_cadence_step(template_id, cadence_step_id):
    db = get_db()
    _get_template(db, template_id)
    db.execute(
        "DELETE FROM pipeline_template_cadence_steps WHERE cadence_step_id = ? AND pipeline_template_id = ? AND tenant_id = ?",
        (cadence_step_id, template_id, g.pipeline_tenant_id),
    )
    db.commit()
    flash("Cadence step deleted.", "success")
    return redirect(url_for("client_acquisition.edit_template", template_id=template_id))
