"""
Module — System Management.

Covers account/session housekeeping (change your own password), whole-
database operations (health check, backups, restore — all gated to
TenantAdmin/SystemAdmin since the one SQLite file holds every tenant's
data), the audit log and its yearly archive-to-CSV, and the Contacts
retention/purge workflow.

GSS v1 has no Employees or External Resources modules (those are TMS/HR-
specific — see PIMS's excluded "Platforms & Subscriptions"/"Services" and
TMS's tourism-only tables), so unlike TMS's system_mgmt.py this file
tracks only contacts_archive for retention/purge, and carries no Host
Organization section at all — GSS has no HR module for a host company
record to belong to.
"""
import csv
import json
import os
import shutil
import sqlite3
from datetime import datetime

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, session, url_for

from auth.decorators import login_required, tenant_admin_required
from security.passwords import hash_password, verify_password
from config import Config
from db import close_db, get_db, log_action

system_mgmt_bp = Blueprint("system_mgmt", __name__)


@system_mgmt_bp.route("/")
@login_required
def index():
    db = get_db()
    tenant_row = db.execute(
        "SELECT tenant_name, data_retention_days, last_purge_at, created_at FROM tenants WHERE tenant_id = ?",
        (g.tenant_id,),
    ).fetchone()
    last_backup_row = db.execute("SELECT MAX(created_at) c FROM backups").fetchone()
    purge_eligible_count = db.execute(
        "SELECT COUNT(*) c FROM contacts_archive WHERE purge_eligible_at IS NOT NULL AND purge_eligible_at <= datetime('now') AND tenant_id = ?",
        (g.tenant_id,),
    ).fetchone()["c"]

    return render_template(
        "system/index.html",
        tenant=tenant_row,
        last_backup_at=last_backup_row["c"],
        purge_eligible_count=purge_eligible_count,
    )


@system_mgmt_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    """Change YOUR OWN login password. Always requires the current password,
    even though the caller is already logged in, so an unattended open
    session can't be used to lock the real owner out.

    This has nothing to do with field encryption — the tenant's DEK is
    independent of any user's password (see security/crypto.py) — so this
    is a plain password_hash update. Nothing else needs to be re-entered
    or re-encrypted."""
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE user_id = ?", (g.user_id,)).fetchone()

        if not verify_password(current_password, user["password_hash"]):
            flash("Current password is incorrect.", "error")
            log_action("PasswordChange", "users", g.user_id, "Failed password change attempt (wrong current password)")
            return render_template("system/change_password.html")

        if len(new_password) < 8:
            flash("New password must be at least 8 characters.", "error")
            return render_template("system/change_password.html")
        if new_password != confirm:
            flash("New passwords do not match.", "error")
            return render_template("system/change_password.html")
        if new_password == current_password:
            flash("New password must be different from your current password.", "error")
            return render_template("system/change_password.html")

        db.execute(
            "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE user_id = ?",
            (hash_password(new_password), g.user_id),
        )
        db.commit()
        log_action("PasswordChange", "users", g.user_id, "Password changed from System Management")
        flash("Password changed.", "success")
        return redirect(url_for("system_mgmt.index"))

    return render_template("system/change_password.html")


# Backups, restore, and the raw database health check touch the WHOLE
# database file (every tenant's data lives in the one SQLite file), so they
# stay gated to admin roles (TenantAdmin or SystemAdmin) rather than any
# logged-in user. In Phase 1's single-tenant desktop deployment the Tenant
# Admin is effectively the sole operator, so tenant_admin_required is used
# here rather than a stricter system_admin_required — tighten this once a
# real multi-tenant deployment introduces a dedicated SystemAdmin/ops role
# distinct from each tenant's own admin.

@system_mgmt_bp.route("/health")
@tenant_admin_required
def health():
    db = get_db()
    integrity = db.execute("PRAGMA integrity_check").fetchall()
    integrity_ok = len(integrity) == 1 and integrity[0][0] == "ok"

    tables = [r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()]
    row_counts = {t: db.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in tables}

    db_size_bytes = os.path.getsize(Config.DATABASE_PATH) if os.path.exists(Config.DATABASE_PATH) else 0

    return render_template(
        "system/health.html",
        integrity_ok=integrity_ok,
        integrity_detail=[r[0] for r in integrity],
        row_counts=row_counts,
        db_size_bytes=db_size_bytes,
    )


@system_mgmt_bp.route("/audit-log")
@tenant_admin_required
def audit_log():
    db = get_db()
    page = max(int(request.args.get("page", 1)), 1)
    per_page = 50
    # Tenant Admins see only their own tenant's audit trail (audit_log.tenant_id
    # is NULL for system-level events, which never belong to a tenant view).
    # audit_log_archives, below, stays a whole-database view by design — it
    # is not filtered here.
    total = db.execute("SELECT COUNT(*) c FROM audit_log WHERE tenant_id = ?", (g.tenant_id,)).fetchone()["c"]
    rows = db.execute(
        "SELECT * FROM audit_log WHERE tenant_id = ? ORDER BY log_id DESC LIMIT ? OFFSET ?",
        (g.tenant_id, per_page, (page - 1) * per_page),
    ).fetchall()
    archivable_count = db.execute(
        "SELECT COUNT(*) c FROM audit_log WHERE ts < datetime('now', '-1 year') AND tenant_id = ?", (g.tenant_id,)
    ).fetchone()["c"]
    archives = db.execute("SELECT * FROM audit_log_archives ORDER BY archive_id DESC").fetchall()
    return render_template(
        "system/audit_log.html",
        rows=rows, page=page, total=total, per_page=per_page,
        archivable_count=archivable_count, archives=archives,
    )


@system_mgmt_bp.route("/audit-log/archive", methods=["POST"])
@tenant_admin_required
def archive_audit_log():
    """Move audit_log entries older than 1 year out to a CSV file, then
    delete them from the live table, so the table itself stays bounded
    over time rather than growing forever. Manual only — nothing purges
    the audit log on its own; the user decides when to run this, the same
    way "Run purge now" works for Contacts.

    This sweeps the whole audit_log table across every tenant in one run
    (like backups, it operates on the one shared database file) — the CSV
    under instance/exports/ is the ONLY remaining copy of those rows
    afterward, and the audit_log_archives row recorded here exists so that
    file stays easy to find and re-download later, mirroring how the
    backups table tracks database backup files.
    """
    db = get_db()
    rows = db.execute(
        "SELECT * FROM audit_log WHERE ts < datetime('now', '-1 year') ORDER BY ts"
    ).fetchall()
    if not rows:
        flash("No audit log entries are older than 1 year yet — nothing to archive.", "success")
        return redirect(url_for("system_mgmt.audit_log"))

    cutoff_ts = db.execute("SELECT datetime('now', '-1 year') c").fetchone()["c"]
    file_name = f"audit_log_archive_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.csv"
    file_path = os.path.join(Config.EXPORTS_DIR, file_name)

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["log_id", "tenant_id", "user_id", "ts", "action", "entity_type", "entity_id", "detail"])
        for r in rows:
            writer.writerow([r["log_id"], r["tenant_id"], r["user_id"], r["ts"], r["action"], r["entity_type"], r["entity_id"], r["detail"]])

    ids = [r["log_id"] for r in rows]
    oldest_ts, newest_ts = rows[0]["ts"], rows[-1]["ts"]

    db.execute(f"DELETE FROM audit_log WHERE log_id IN ({','.join('?' * len(ids))})", ids)
    db.execute(
        "INSERT INTO audit_log_archives (file_name, file_path, row_count, oldest_ts, newest_ts, cutoff_ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (file_name, file_path, len(ids), oldest_ts, newest_ts, cutoff_ts),
    )
    db.commit()

    # Logged from a fresh timestamp AFTER the delete, so this entry about
    # the archive run is never itself among the rows it just archived.
    log_action("Archive", "audit_log", None, f"Archived {len(ids)} audit log entries (older than {cutoff_ts}) to {file_name}")

    flash(f"Archived {len(ids)} entries older than 1 year to {file_name}.", "success")
    return redirect(url_for("system_mgmt.audit_log"))


@system_mgmt_bp.route("/audit-log/archive/<int:archive_id>/download")
@tenant_admin_required
def download_audit_archive(archive_id):
    db = get_db()
    a = db.execute("SELECT * FROM audit_log_archives WHERE archive_id = ?", (archive_id,)).fetchone()
    if a is None or not os.path.exists(a["file_path"]):
        abort(404)
    return send_file(a["file_path"], as_attachment=True, download_name=a["file_name"], mimetype="text/csv")


@system_mgmt_bp.route("/retention", methods=["POST"])
@tenant_admin_required
def update_retention():
    days = request.form.get("data_retention_days", "").strip()
    db = get_db()
    if days == "":
        # Blank = indefinite retention (never auto-purge).
        db.execute(
            "UPDATE tenants SET data_retention_days = NULL, updated_at = datetime('now') WHERE tenant_id = ?",
            (g.tenant_id,),
        )
        db.commit()
        log_action("Update", "tenants", g.tenant_id, "Retention window set to indefinite")
        flash("Retention window set to indefinite — archived records will never be auto-purged.", "success")
        return redirect(url_for("system_mgmt.index"))

    if not days.isdigit() or int(days) < 1:
        flash("Retention window must be a positive number of days, or left blank for indefinite.", "error")
        return redirect(url_for("system_mgmt.index"))

    db.execute(
        "UPDATE tenants SET data_retention_days = ?, updated_at = datetime('now') WHERE tenant_id = ?",
        (int(days), g.tenant_id),
    )
    db.commit()
    log_action("Update", "tenants", g.tenant_id, f"Retention window set to {days} days")
    flash("Retention window updated.", "success")
    return redirect(url_for("system_mgmt.index"))


# --------------------------------------------------------------- purge

def _purge_eligible(db):
    """Permanently erase every contact whose archived snapshot has passed
    its retention window (contacts_archive.purge_eligible_at <= now).

    This is real, irreversible deletion — unlike delete_contact()'s
    soft-delete, which only sets is_deleted=1 and leaves everything else in
    place for a possible restore. Purge removes: the archive snapshot
    itself, every live child row still hanging off the contact (emails,
    phones, addresses, reference links), every history row that logs a
    change to one of those (deleted first, since they carry their own
    foreign keys down into the child rows), and finally the contacts row
    itself. Anything elsewhere that still points at the contact is detached
    first so the delete doesn't trip PRAGMA foreign_keys = ON:
      - another contact that named this one as its Assistant
      - a Content item's "Contacts Link" pointing at this contact (the link
        row is kept, with contact_id cleared, if it also carries a URL —
        otherwise the link row itself is removed, since a Contacts Link
        can't point at nothing)

    Returns the list of full_names purged (for a flash message / log
    detail); each purge is also written to audit_log individually.

    Scoped to the CURRENT tenant only — this runs for a specific tenant's
    session (either from purge_now(), behind login_required, or from the
    opportunistic login-time check in maybe_run_daily_purge()), and every
    table touched here is tenant-owned, so a purge must never reach across
    into another tenant's archived contacts. Reads the tenant from the
    Flask session directly (rather than g.tenant_id) so it also works from
    the login flow, which calls this before login_required's g.* setup
    would normally run.

    GSS has no Employees/External Resources modules, so — unlike TMS's
    version of this function — there is nothing to purge beyond Contacts.
    """
    tenant_id = session.get("tenant_id")
    if not tenant_id:
        # No tenant context (e.g. a SystemAdmin login) — nothing tenant-owned
        # to purge.
        return []

    rows = db.execute(
        "SELECT contact_id, snapshot FROM contacts_archive "
        "WHERE purge_eligible_at IS NOT NULL AND purge_eligible_at <= datetime('now') AND tenant_id = ?",
        (tenant_id,),
    ).fetchall()

    purged_names = []
    for row in rows:
        cid = row["contact_id"]
        try:
            name = json.loads(row["snapshot"]).get("contact", {}).get("full_name") or f"contact #{cid}"
        except (ValueError, TypeError):
            name = f"contact #{cid}"

        # Detach anything outside this contact's own rows that still points at it.
        db.execute(
            "UPDATE contacts SET assistant_contact_id = NULL WHERE assistant_contact_id = ? AND tenant_id = ?",
            (cid, tenant_id),
        )
        db.execute(
            "UPDATE content_contact_links SET contact_id = NULL WHERE contact_id = ? AND url IS NOT NULL AND tenant_id = ?",
            (cid, tenant_id),
        )
        db.execute(
            "DELETE FROM content_contact_links WHERE contact_id = ? AND url IS NULL AND tenant_id = ?", (cid, tenant_id)
        )

        # History rows first (they carry their own FKs into the child tables below).
        db.execute("DELETE FROM contact_emails_history WHERE contact_id = ? AND tenant_id = ?", (cid, tenant_id))
        db.execute("DELETE FROM contact_phones_history WHERE contact_id = ? AND tenant_id = ?", (cid, tenant_id))
        db.execute(
            "DELETE FROM addresses_history WHERE owner_type = 'Contact' AND owner_id = ? AND tenant_id = ?",
            (cid, tenant_id),
        )
        db.execute("DELETE FROM contacts_history WHERE contact_id = ? AND tenant_id = ?", (cid, tenant_id))

        # The contact's own live child rows.
        db.execute("DELETE FROM contact_emails WHERE contact_id = ? AND tenant_id = ?", (cid, tenant_id))
        db.execute("DELETE FROM contact_phones WHERE contact_id = ? AND tenant_id = ?", (cid, tenant_id))
        db.execute(
            "DELETE FROM addresses WHERE owner_type = 'Contact' AND owner_id = ? AND tenant_id = ?", (cid, tenant_id)
        )
        db.execute("DELETE FROM contact_reference_links WHERE contact_id = ? AND tenant_id = ?", (cid, tenant_id))

        # The archive snapshot and the (already soft-deleted) live row itself.
        db.execute("DELETE FROM contacts_archive WHERE contact_id = ? AND tenant_id = ?", (cid, tenant_id))
        db.execute("DELETE FROM contacts WHERE contact_id = ? AND tenant_id = ?", (cid, tenant_id))

        log_action("Purge", "contact", cid, f"Purged '{name}' — past its configured retention window",
                   tenant_id=tenant_id)
        purged_names.append(name)

    db.commit()
    return purged_names


def maybe_run_daily_purge(db):
    """Opportunistic trigger, called once at login: run the purge check at
    most once per calendar day for the CURRENT tenant (this app has no
    background scheduler of its own and only runs while someone has it
    open). Updates tenants.last_purge_at every time the check itself runs
    (even if nothing was eligible), so "once per day, per tenant" works
    without needing a separate tracking table."""
    tenant_id = session.get("tenant_id")
    if not tenant_id:
        return None

    row = db.execute("SELECT last_purge_at FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone()
    last = row["last_purge_at"] if row else None
    if last:
        already_today = db.execute(
            "SELECT date(?) = date('now') AS same_day", (last,)
        ).fetchone()["same_day"]
        if already_today:
            return None

    purged = _purge_eligible(db)
    db.execute("UPDATE tenants SET last_purge_at = datetime('now') WHERE tenant_id = ?", (tenant_id,))
    db.commit()
    return purged


@system_mgmt_bp.route("/purge-now", methods=["POST"])
@tenant_admin_required
def purge_now():
    db = get_db()
    purged = _purge_eligible(db)
    db.execute("UPDATE tenants SET last_purge_at = datetime('now') WHERE tenant_id = ?", (g.tenant_id,))
    db.commit()
    if purged:
        flash(f"Purged {len(purged)} record(s) past their retention window: {', '.join(purged)}.", "success")
    else:
        flash("Nothing was eligible for purge.", "success")
    return redirect(url_for("system_mgmt.index"))


# --------------------------------------------------------------- backups

def _table_stats(db):
    """(table_count, total_rows) across every real table — the same
    row-count sweep Database Health already does, reused here so each
    backup's log entry records what it actually contained."""
    tables = [r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()]
    total_rows = sum(db.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"] for t in tables)
    return len(tables), total_rows


def _integrity_ok(db):
    integrity = db.execute("PRAGMA integrity_check").fetchall()
    return 1 if (len(integrity) == 1 and integrity[0][0] == "ok") else 0


def _write_backup_file(db, file_name):
    """Copy the live database to instance/backups/<file_name> using
    SQLite's online backup API — safe against a live connection (it won't
    race an in-flight write the way a raw file copy could), unlike
    shutil.copy on its own."""
    file_path = os.path.join(Config.BACKUPS_DIR, file_name)
    # Defensive uniqueness check: two backups in the same microsecond is
    # astronomically unlikely, but backup() would silently overwrite an
    # existing same-named file rather than erroring, so a real collision
    # here would otherwise fail silently instead of loudly.
    stem, ext = os.path.splitext(file_path)
    n = 1
    while os.path.exists(file_path):
        file_path = f"{stem}_{n}{ext}"
        n += 1
    dest = sqlite3.connect(file_path)
    try:
        db.backup(dest)
    finally:
        dest.close()
    return file_path, os.path.getsize(file_path)


@system_mgmt_bp.route("/backups")
@tenant_admin_required
def backups_index():
    db = get_db()
    rows = db.execute("SELECT * FROM backups ORDER BY backup_id DESC").fetchall()
    db_size_bytes = os.path.getsize(Config.DATABASE_PATH) if os.path.exists(Config.DATABASE_PATH) else 0
    return render_template("system/backups.html", backups=rows, db_size_bytes=db_size_bytes)


@system_mgmt_bp.route("/backups/create", methods=["POST"])
@tenant_admin_required
def create_backup():
    db = get_db()
    file_name = f"gss_backup_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db"
    file_path, size_bytes = _write_backup_file(db, file_name)
    file_name = os.path.basename(file_path)  # _write_backup_file may have deduplicated the name
    table_count, total_rows = _table_stats(db)
    integrity_ok = _integrity_ok(db)

    db.execute(
        """INSERT INTO backups (file_name, file_path, size_bytes, table_count, total_rows, integrity_ok, backup_type)
           VALUES (?, ?, ?, ?, ?, ?, 'Manual')""",
        (file_name, file_path, size_bytes, table_count, total_rows, integrity_ok),
    )
    db.commit()
    backup_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    log_action("Backup", "backup", backup_id, f"Created backup {file_name} ({size_bytes} bytes)")
    flash(f"Backup created: {file_name}", "success")
    return redirect(url_for("system_mgmt.backups_index"))


@system_mgmt_bp.route("/backups/<int:backup_id>/download")
@tenant_admin_required
def download_backup(backup_id):
    db = get_db()
    b = db.execute("SELECT * FROM backups WHERE backup_id = ?", (backup_id,)).fetchone()
    if b is None or not os.path.exists(b["file_path"]):
        abort(404)
    return send_file(b["file_path"], as_attachment=True, download_name=b["file_name"], mimetype="application/octet-stream")


@system_mgmt_bp.route("/backups/<int:backup_id>/restore", methods=["POST"])
@tenant_admin_required
def restore_backup(backup_id):
    db = get_db()
    b = db.execute("SELECT * FROM backups WHERE backup_id = ?", (backup_id,)).fetchone()
    if b is None or not os.path.exists(b["file_path"]):
        flash("That backup file could not be found on disk.", "error")
        return redirect(url_for("system_mgmt.backups_index"))

    # Safety net: snapshot the CURRENT database before overwriting it, so a
    # restore is itself undoable. Its log row is written after the swap
    # (see below) — one written now would just be lost, since restoring
    # replaces the whole backups table along with everything else.
    safety_name = f"gss_backup_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_pre_restore.db"
    safety_path, safety_size = _write_backup_file(db, safety_name)
    safety_name = os.path.basename(safety_path)  # _write_backup_file may have deduplicated the name
    safety_table_count, safety_total_rows = _table_stats(db)
    safety_integrity_ok = _integrity_ok(db)

    # Flask opens a fresh sqlite3.Connection per request (see get_db()) —
    # no long-lived connection to worry about beyond this one, so closing
    # it here is enough to safely swap the file out from under it.
    close_db()
    tmp_path = Config.DATABASE_PATH + ".tmp_restore"
    shutil.copy2(b["file_path"], tmp_path)
    os.replace(tmp_path, Config.DATABASE_PATH)  # atomic on the same volume

    # Re-open against the now-restored database and append two rows to its
    # (reverted) backups log: the safety snapshot just taken, and a
    # provenance marker recording what was just restored from — otherwise
    # both facts would be invisible since the log itself just rolled back.
    db = get_db()
    db.execute(
        """INSERT INTO backups (file_name, file_path, size_bytes, table_count, total_rows, integrity_ok, backup_type, notes)
           VALUES (?, ?, ?, ?, ?, ?, 'Pre-restore safety', ?)""",
        (safety_name, safety_path, safety_size, safety_table_count, safety_total_rows, safety_integrity_ok,
         "Automatic snapshot of the database as it was immediately before this restore."),
    )
    db.execute(
        """INSERT INTO backups (file_name, file_path, size_bytes, table_count, total_rows, integrity_ok, backup_type, notes)
           VALUES (?, ?, ?, ?, ?, ?, 'Restore point', ?)""",
        (b["file_name"], b["file_path"], b["size_bytes"], b["table_count"], b["total_rows"], b["integrity_ok"],
         f"Database restored from this backup (originally created {b['created_at']})."),
    )
    db.commit()
    log_action("Restore", "database", None,
               f"Restored database from {b['file_name']} (originally created {b['created_at']}); "
               f"safety snapshot saved as {safety_name}")

    # The whole database file was just swapped out from under this session
    # — clearest and safest thing to do is log everyone out and have them
    # sign back in against whatever the restored database actually holds.
    session.clear()
    flash(f"Database restored from backup taken {b['created_at']}. A safety snapshot of what was just replaced "
          f"was saved as {safety_name}. Please log in again.", "success")
    return redirect(url_for("auth_bp.login"))


@system_mgmt_bp.route("/backups/<int:backup_id>/delete", methods=["POST"])
@tenant_admin_required
def delete_backup(backup_id):
    db = get_db()
    b = db.execute("SELECT * FROM backups WHERE backup_id = ?", (backup_id,)).fetchone()
    if b is None:
        abort(404)
    if os.path.exists(b["file_path"]):
        os.remove(b["file_path"])
    db.execute("DELETE FROM backups WHERE backup_id = ?", (backup_id,))
    db.commit()
    log_action("Delete", "backup", backup_id, f"Deleted backup {b['file_name']}")
    flash("Backup deleted.", "success")
    return redirect(url_for("system_mgmt.backups_index"))
