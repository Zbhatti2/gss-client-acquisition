"""
Outbound email — currently used for exactly one thing: notifying a tenant's
configured lead_notification_email address when their public website's
contact form creates a new Opportunity (see blueprints/public_leads.py and
System Management's Lead Intake config, blueprints/system_mgmt.py).

No email-sending existed anywhere in GSS before this. Deliberately plain
smtplib -- no Flask-Mail, no provider SDK -- configured entirely via
environment variables, same "optional feature, off by default, degrades
gracefully" shape as ANTHROPIC_API_KEY in business_card_import.py/
ad_import.py. The difference from that pattern: those raise on a missing
key because the feature they gate is something a logged-in user just
clicked "Extract" on and needs to see fail. Sending a lead notification is
a background side-effect of a public form submission with nobody watching
for an exception, so an unconfigured or failing SMTP setup here logs a
warning and returns False instead of raising -- the Organization/Contact/
Opportunity the lead form created must never be rolled back just because
notification email isn't set up yet.

Required environment variables (all unset = feature off, send_lead_notification
returns False immediately without attempting a connection):
    SMTP_HOST           e.g. smtp.hostinger.com
    SMTP_PORT           e.g. 587 (STARTTLS) or 465 (implicit TLS) -- default 587
    SMTP_USERNAME
    SMTP_PASSWORD
    SMTP_FROM_ADDRESS   the From: header; falls back to SMTP_USERNAME if unset
"""
import os
import smtplib
from email.message import EmailMessage

from flask import current_app


def _smtp_settings():
    """Returns a dict of settings if the minimum required env vars are
    present, else None. Doesn't validate the values are actually correct
    (a bad host/password is a connect-time failure, reported by
    send_lead_notification's caller-facing return value, not here)."""
    host = os.environ.get("SMTP_HOST")
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    if not (host and username and password):
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "username": username,
        "password": password,
        "from_address": os.environ.get("SMTP_FROM_ADDRESS") or username,
    }


def is_configured() -> bool:
    """Cheap check for UI purposes (e.g. System Management's Lead Intake
    card can show "email delivery: not yet configured on the server" next
    to the per-tenant notification-address field, without attempting a
    connection)."""
    return _smtp_settings() is not None


def send_lead_notification(to_address: str, tenant_name: str, organization_name: str,
                            contact_name: str, contact_email: str, contact_phone: str,
                            message: str) -> bool:
    """Sends a plain-text "new lead" notification. Returns True on success,
    False on any failure (unconfigured server, bad credentials, network
    error, invalid to_address) -- always logged via current_app.logger,
    never raised, per this module's docstring. Callers (blueprints/
    public_leads.py) must treat a False return as "the lead was still
    saved, only the email didn't go out" and respond to the website
    accordingly, not as a request failure."""
    settings = _smtp_settings()
    if not settings:
        current_app.logger.warning(
            "send_lead_notification: SMTP is not configured (SMTP_HOST/SMTP_USERNAME/"
            "SMTP_PASSWORD env vars) -- skipping email for a new lead from %r", organization_name
        )
        return False
    if not to_address:
        current_app.logger.warning(
            "send_lead_notification: tenant %r has no lead_notification_email configured "
            "-- skipping email for a new lead from %r", tenant_name, organization_name
        )
        return False

    msg = EmailMessage()
    msg["Subject"] = f"New website lead: {organization_name}"
    msg["From"] = settings["from_address"]
    msg["To"] = to_address
    msg.set_content(
        f"A new lead came in through the {tenant_name} website's contact form and has "
        f"been added to Client Acquisition as a new Opportunity.\n\n"
        f"Organization: {organization_name}\n"
        f"Contact: {contact_name or '(not given)'}\n"
        f"Email: {contact_email or '(not given)'}\n"
        f"Phone: {contact_phone or '(not given)'}\n\n"
        f"Message:\n{message or '(none)'}\n"
    )

    try:
        if settings["port"] == 465:
            server = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=15)
        else:
            server = smtplib.SMTP(settings["host"], settings["port"], timeout=15)
        with server:
            if settings["port"] != 465:
                server.starttls()
            server.login(settings["username"], settings["password"])
            server.send_message(msg)
        return True
    except Exception:
        current_app.logger.exception(
            "send_lead_notification: failed to send lead-notification email to %r for tenant %r",
            to_address, tenant_name
        )
        return False
