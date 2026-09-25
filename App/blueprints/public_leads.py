"""
Public, unauthenticated lead-intake endpoint — the first route in GSS that
isn't gated by a session login (every other route uses login_required /
tenant_admin_required / system_admin_required from auth/decorators.py).

It exists so a tenant's own public marketing website (e.g.
www.granitesignalsystems.com, a separate static site — not part of this
Flask app) can POST its contact-form submissions straight into that
tenant's Client Acquisition pipeline as a new Organization + Contact +
Opportunity, with no GSS account and no session cookie involved at all.

Authentication model: instead of a session, each tenant has its own opaque
lead_intake_token (schema.sql's tenants.lead_intake_token — generated for
every tenant at provisioning time by tenant_provisioning.py, and viewable/
regenerable by a TenantAdmin from System Management's Lead Intake config,
see blueprints/system_mgmt.py's lead_intake_config()). The token is
embedded directly in that tenant's public website's client-side JavaScript,
so anyone who views that page's source can read it — this is a known,
accepted trade-off, not an oversight: the token authorizes exactly one
thing, "create one Opportunity for this tenant", nothing else. It grants no
read access to any tenant data (this module has no GET routes) and can't
reach any OTHER tenant's data either (the token itself is looked up, not
the tenant_code, so it isn't even guessable from a tenant's public name).
If that scope ever needs to tighten further — rate limiting, locking to a
specific Origin, a CAPTCHA — this module is the one place to add it.

CSRF: exempted in security/csrf.py's CSRF_EXEMPT_ENDPOINTS — see that
module's comment for why a bearer-token-authenticated, non-session route
has nothing for CSRF to exploit in the first place.

CORS: handled by hand below (no flask-cors dependency, matching this
codebase's preference for stdlib over new packages where practical) since
this is the only blueprint in GSS ever meant to be called cross-origin.
"""
import os

from flask import Blueprint, g, jsonify, request

from db import get_db, log_action

import email_notify

public_leads_bp = Blueprint("public_leads", __name__)

# The real website's contact form (website/js/contact-form.js) never shows
# or fills this field -- a human visitor never populates it, so any
# submission that arrives with it non-empty is a bot. Reported back as a
# plain success (so the bot has no signal telling it to retry/escalate)
# without creating anything or sending any notification email.
HONEYPOT_FIELD = "website"

MAX_FIELD_LENGTH = 500
MAX_MESSAGE_LENGTH = 5000


def _cors_allowed_origin() -> str:
    """'*' by default -- the token, not the calling Origin, is what
    actually authorizes this endpoint (see module docstring), so there's
    no security reason to restrict it out of the gate. If LEAD_INTAKE_
    ALLOWED_ORIGINS (comma-separated) is set in the environment, only an
    Origin on that list is ever echoed back instead -- set this once real
    production domains are finalized, for defense-in-depth on top of the
    token."""
    allowed = os.environ.get("LEAD_INTAKE_ALLOWED_ORIGINS", "").strip()
    if not allowed:
        return "*"
    origin = request.headers.get("Origin", "")
    allowed_list = {o.strip() for o in allowed.split(",") if o.strip()}
    return origin if origin in allowed_list else "null"


@public_leads_bp.after_request
def _add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = _cors_allowed_origin()
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "600"
    return response


def _clean(value, max_len=MAX_FIELD_LENGTH) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_len]


@public_leads_bp.route("/leads", methods=["POST", "OPTIONS"])
def submit_lead():
    if request.method == "OPTIONS":
        # CORS preflight -- browsers send this ahead of the real POST
        # because the real request uses Content-Type: application/json.
        # Nothing to authenticate or process here, just acknowledge it;
        # _add_cors_headers above (an after_request hook, so it also runs
        # on this response) supplies the actual Allow-* headers.
        return "", 204

    payload = request.get_json(silent=True) or {}

    token = _clean(payload.get("token"), 200)
    if not token:
        return jsonify(ok=False, error="Missing token."), 401

    db = get_db()
    tenant = db.execute(
        "SELECT tenant_id, tenant_name, lead_notification_email, status "
        "FROM tenants WHERE lead_intake_token = ? AND is_platform = 0",
        (token,),
    ).fetchone()
    if tenant is None:
        return jsonify(ok=False, error="Invalid token."), 401
    if tenant["status"] != "Active":
        # Suspended/inactive tenant -- accept nothing further, but don't
        # tell an anonymous caller *why* beyond that.
        return jsonify(ok=False, error="This form is not currently accepting submissions."), 403

    if _clean(payload.get(HONEYPOT_FIELD)):
        return jsonify(ok=True), 200

    organization_name = _clean(payload.get("organization_name"))
    contact_name = _clean(payload.get("contact_name"))
    contact_email = _clean(payload.get("contact_email"))
    contact_phone = _clean(payload.get("contact_phone"), 50)
    message = _clean(payload.get("message"), MAX_MESSAGE_LENGTH)

    if not organization_name:
        return jsonify(ok=False, error="Organization/company name is required."), 400
    if not (contact_name or contact_email or contact_phone):
        return jsonify(ok=False, error="Please provide a name, email, or phone number so we can reach you."), 400

    tenant_id = tenant["tenant_id"]

    # Find-or-create the Organization by name within this tenant, same
    # convention as the CSV/ad-import paths in blueprints/data_exchange.py.
    org_row = db.execute(
        "SELECT organization_id FROM organizations WHERE tenant_id = ? AND organization_name = ? COLLATE NOCASE",
        (tenant_id, organization_name),
    ).fetchone()
    if org_row:
        organization_id = org_row["organization_id"]
    else:
        cur = db.execute(
            "INSERT INTO organizations (tenant_id, organization_name, email, phone) VALUES (?, ?, ?, ?)",
            (tenant_id, organization_name, contact_email or None, contact_phone or None),
        )
        organization_id = cur.lastrowid
    db.commit()

    full_name = contact_name or contact_email or contact_phone or "Website Lead"
    cur = db.execute(
        "INSERT INTO contacts (tenant_id, full_name, current_organization_id) VALUES (?, ?, ?)",
        (tenant_id, full_name, organization_id),
    )
    contact_id = cur.lastrowid
    if contact_email:
        db.execute(
            "INSERT INTO contact_emails (tenant_id, contact_id, email_address, is_primary) VALUES (?, ?, ?, 1)",
            (tenant_id, contact_id, contact_email),
        )
    if contact_phone:
        db.execute(
            "INSERT INTO contact_phones (tenant_id, contact_id, phone_type, number, is_primary) VALUES (?, ?, 'Business', ?, 1)",
            (tenant_id, contact_id, contact_phone),
        )
    db.commit()

    # Opportunity, in the tenant's first active pipeline template -- same
    # shape (stage history + checklist snapshot + cadence tasks) that a
    # manual "New Opportunity" in the app itself produces (see
    # blueprints/client_acquisition.py's new_opportunity()), so a website
    # lead looks and behaves exactly like one entered by hand.
    template = db.execute(
        "SELECT pipeline_template_id FROM pipeline_templates WHERE tenant_id = ? AND is_active = 1 "
        "ORDER BY sort_order LIMIT 1",
        (tenant_id,),
    ).fetchone()

    opportunity_id = None
    if template:
        first_stage = db.execute(
            "SELECT * FROM pipeline_template_stages WHERE pipeline_template_id = ? ORDER BY stage_number LIMIT 1",
            (template["pipeline_template_id"],),
        ).fetchone()
        opp_name = f"{organization_name} — Website Inquiry"
        cur = db.execute(
            """INSERT INTO opportunities
               (tenant_id, organization_id, pipeline_template_id, opportunity_name,
                current_stage_number, probability_percent, lead_source, lead_source_detail)
               VALUES (?, ?, ?, ?, ?, ?, 'Website', ?)""",
            (
                tenant_id, organization_id, template["pipeline_template_id"], opp_name,
                first_stage["stage_number"] if first_stage else 1,
                first_stage["probability_percent"] if first_stage else 0,
                message or None,
            ),
        )
        opportunity_id = cur.lastrowid
        db.commit()

        if first_stage:
            # These three helpers are written against g.tenant_id/g.user_id
            # (the normal request-scoped globals login_required sets — see
            # auth/decorators.py) rather than taking them as arguments, so
            # they're set here to the same effect for this token-
            # authenticated, session-less request. Both stage_history.
            # changed_by_user_id and tasks.assigned_user_id are nullable
            # (schema.sql) precisely because "no user did this" is a real,
            # expected case, e.g. a Cadence-generated task -- so g.user_id
            # = None here is not a workaround, it's the correct value: no
            # GSS user, a website visitor, created this.
            from blueprints.client_acquisition import (
                _generate_cadence_tasks,
                _record_stage_history,
                _snapshot_checklist,
            )
            g.tenant_id = tenant_id
            g.user_id = None
            now = db.execute("SELECT datetime('now') n").fetchone()["n"]
            _record_stage_history(
                db, opportunity_id, None, None, "Active", first_stage["stage_number"],
                None, first_stage["probability_percent"], False, None,
            )
            _snapshot_checklist(db, opportunity_id, template["pipeline_template_id"], first_stage["stage_number"])
            _generate_cadence_tasks(
                db, opportunity_id, template["pipeline_template_id"], first_stage["stage_number"], now, None,
            )
            db.commit()

    log_action(
        "Create", "opportunity", opportunity_id,
        f"Website lead intake: new organization '{organization_name}'" + (
            f", opportunity #{opportunity_id}" if opportunity_id else " (no active pipeline template -- opportunity not created)"
        ),
        tenant_id=tenant_id, user_id=None,
    )

    # Best-effort -- a failed/unconfigured send never rolls back or fails
    # the lead itself (see email_notify.py's module docstring).
    email_notify.send_lead_notification(
        to_address=tenant["lead_notification_email"],
        tenant_name=tenant["tenant_name"],
        organization_name=organization_name,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        message=message,
    )

    return jsonify(ok=True), 201
