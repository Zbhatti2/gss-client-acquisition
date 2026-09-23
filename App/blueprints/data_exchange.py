"""
Module — Data Exchange (Import / Export Staging).

Import: files are never written straight into the live tables. A CSV
upload becomes an import_batches row plus one import_staging_rows row per
source row (raw_data as JSON); each staging row is validated, the batch is
shown for review, and only on an explicit "Commit" does anything reach the
live tables — following the same history-aware insert pattern the
Contacts/Organizations modules use. GSS v1 ships importers for Contacts and
Organizations (its two record-holding modules); Documents & Knowledge Base
has no importer of its own yet.

Export: every download is recorded as an export_jobs row with the file
written under instance/exports/, then served back for download — so
"what got exported and when" has an audit trail, not just an in-memory
CSV stream.

Sensitive fields ARE decrypted into JSON/CSV exports (this is your own
backup of your own data) — the UI warns that exported files are plaintext
and should be stored/deleted carefully.
"""
import csv
import io
import json
import os
import re
import time
import uuid
import zipfile

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, send_from_directory, url_for

from ad_import import ExtractionError as AdExtractionError
from ad_import import extract_ads_for_import, iter_images_from_zip
from agents import agent_access_required, log_agent_usage
from auth.decorators import login_required
from blueprints.contacts import _delete_image_upload
from blueprints.organizations import (
    MAX_BATCH_AD_IMAGES,
    _add_ad_note,
    _ad_dict_from_extracted,
    _attach_ad_photo_file,
    _cleanup_stale_pending_ads,
    _create_ad_listing,
    _find_ad_listing_by_headline,
    _pending_ad_path,
    _promote_pending_ad_image,
    _save_pending_ad_image,
    _update_ad_listing_partial,
)
from business_card_import import (
    CONTACT_PHONE_TYPES,
    ExtractionError,
    _classify_contact_phone_label,
    _classify_org_phone_label,
    extract_business_card,
)
from config import Config
from db import get_db, log_action
from geo_matching import extract_trailing_phones, match_city, match_country, match_state, parse_free_text_address
from seed_data import _slug
from security import crypto

data_exchange_bp = Blueprint("data_exchange", __name__)


@data_exchange_bp.route("/")
@login_required
def index():
    db = get_db()
    batches = db.execute(
        "SELECT * FROM import_batches WHERE tenant_id = ? ORDER BY batch_id DESC LIMIT 20", (g.tenant_id,)
    ).fetchall()
    jobs = db.execute(
        "SELECT * FROM export_jobs WHERE tenant_id = ? ORDER BY export_id DESC LIMIT 20", (g.tenant_id,)
    ).fetchall()
    return render_template("data_exchange/index.html", batches=batches, jobs=jobs)


# =============================================================== EXPORT ===

def _dec(ct, dek):
    try:
        return crypto.decrypt_value(ct, dek)
    except ValueError:
        return None


def _export_contacts_rows(db):
    contacts = db.execute(
        "SELECT * FROM contacts WHERE is_deleted = 0 AND tenant_id = ? ORDER BY full_name", (g.tenant_id,)
    ).fetchall()
    rows = []
    for c in contacts:
        emails = db.execute("SELECT email_address FROM contact_emails WHERE contact_id = ?", (c["contact_id"],)).fetchall()
        phones = db.execute("SELECT phone_type, country_code, area_code, number, extension FROM contact_phones WHERE contact_id = ?", (c["contact_id"],)).fetchall()
        rows.append({
            "full_name": c["full_name"], "file_as": c["file_as"], "job_title": c["current_job_title"],
            "web_page": c["web_page"], "date_of_birth": c["date_of_birth"], "notes": c["notes"],
            "emails": [e["email_address"] for e in emails],
            "phones": [f"{p['phone_type']}: {p['country_code'] or ''} {p['area_code'] or ''} {p['number']}".strip() for p in phones],
        })
    return rows


def _export_organizations_rows(db):
    orgs = db.execute(
        "SELECT * FROM organizations WHERE tenant_id = ? ORDER BY organization_name", (g.tenant_id,)
    ).fetchall()
    out = []
    for o in orgs:
        d = dict(o)
        d["addresses"] = [dict(r) for r in db.execute(
            "SELECT street, unit, state_province_text, city_text, postal_code FROM organization_addresses WHERE organization_id = ?",
            (o["organization_id"],),
        ).fetchall()]
        d["emails"] = [r["email_address"] for r in db.execute(
            "SELECT email_address FROM organization_emails WHERE organization_id = ?", (o["organization_id"],)
        ).fetchall()]
        d["phones"] = [r["number"] for r in db.execute(
            "SELECT number FROM organization_phones WHERE organization_id = ?", (o["organization_id"],)
        ).fetchall()]
        out.append(d)
    return out


def _export_documents_rows(db):
    items = db.execute(
        "SELECT * FROM content WHERE is_deleted = 0 AND tenant_id = ?", (g.tenant_id,)
    ).fetchall()
    out = []
    for i in items:
        d = dict(i)
        d["locations"] = [dict(r) for r in db.execute("SELECT location_type, path_or_url FROM content_locations WHERE content_id = ?", (i["content_id"],)).fetchall()]
        d["keywords"] = [r["term"] for r in db.execute("SELECT term FROM content_keywords WHERE content_id = ?", (i["content_id"],)).fetchall()]
        d["hashtags"] = [r["term"] for r in db.execute("SELECT term FROM content_hashtags WHERE content_id = ?", (i["content_id"],)).fetchall()]
        out.append(d)
    return out


def _export_json(module, db, dek):
    if module == "contacts":
        return _export_contacts_rows(db)
    if module == "organizations":
        return _export_organizations_rows(db)
    if module == "documents":
        return _export_documents_rows(db)
    abort(404)


def _contacts_csv_bytes(db):
    rows = _export_contacts_rows(db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["full_name", "file_as", "job_title", "web_page", "date_of_birth", "email", "phone", "notes"])
    for r in rows:
        writer.writerow([r["full_name"], r["file_as"] or "", r["job_title"] or "", r["web_page"] or "",
                          r["date_of_birth"] or "", "; ".join(r["emails"]), "; ".join(r["phones"]), r["notes"] or ""])
    return buf.getvalue().encode("utf-8")


def _contacts_vcard_bytes(db):
    contacts = db.execute(
        "SELECT * FROM contacts WHERE is_deleted = 0 AND tenant_id = ? ORDER BY full_name", (g.tenant_id,)
    ).fetchall()
    lines = []
    for c in contacts:
        emails = db.execute("SELECT email_address FROM contact_emails WHERE contact_id = ?", (c["contact_id"],)).fetchall()
        phones = db.execute("SELECT number FROM contact_phones WHERE contact_id = ?", (c["contact_id"],)).fetchall()
        lines.append("BEGIN:VCARD")
        lines.append("VERSION:3.0")
        lines.append(f"FN:{c['full_name']}")
        lines.append(f"N:{c['full_name']};;;;")
        for e in emails:
            lines.append(f"EMAIL:{e['email_address']}")
        for p in phones:
            lines.append(f"TEL:{p['number']}")
        if c["notes"]:
            lines.append(f"NOTE:{c['notes'].replace(chr(10), ' ')}")
        lines.append("END:VCARD")
    return "\r\n".join(lines).encode("utf-8")


def _organizations_csv_bytes(db):
    rows = _export_organizations_rows(db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["organization_name", "type_id", "website", "email", "phone", "notes"])
    for r in rows:
        writer.writerow([
            r["organization_name"], r.get("organization_type_id") or "", r.get("website") or "",
            "; ".join(r["emails"]), "; ".join(r["phones"]), r.get("notes") or "",
        ])
    return buf.getvalue().encode("utf-8")


EXPORT_FORMATS = {
    "contacts": ["json", "csv", "vcard"],
    "organizations": ["json", "csv"],
    "documents": ["json"],
}
EXT = {"json": "json", "csv": "csv", "vcard": "vcf"}
MIME = {"json": "application/json", "csv": "text/csv", "vcard": "text/vcard"}
# schema.sql's export_jobs.format CHECK constraint expects this exact casing
# ('CSV','JSON','vCard','PDF') — the rest of this module works with the
# lowercase form throughout, so translate only at the point of insert.
FORMAT_DB_LABEL = {"json": "JSON", "csv": "CSV", "vcard": "vCard"}


@data_exchange_bp.route("/export", methods=["POST"])
@login_required
def create_export():
    module = request.form.get("module")
    fmt = request.form.get("format")
    if module not in EXPORT_FORMATS or fmt not in EXPORT_FORMATS[module]:
        abort(400)

    db = get_db()
    if fmt == "json":
        data = _export_json(module, db, g.dek)
        content = json.dumps(data, indent=2, default=str).encode("utf-8")
    elif fmt == "csv" and module == "contacts":
        content = _contacts_csv_bytes(db)
    elif fmt == "csv" and module == "organizations":
        content = _organizations_csv_bytes(db)
    elif fmt == "vcard" and module == "contacts":
        content = _contacts_vcard_bytes(db)
    else:
        abort(400)

    filename = f"{module}.{EXT[fmt]}"
    db.execute(
        "INSERT INTO export_jobs (tenant_id, module, format, file_path) VALUES (?, ?, ?, ?)",
        (g.tenant_id, module, FORMAT_DB_LABEL[fmt], filename),
    )
    db.commit()
    export_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]

    file_path = os.path.join(Config.EXPORTS_DIR, f"{export_id}_{filename}")
    with open(file_path, "wb") as f:
        f.write(content)
    db.execute(
        "UPDATE export_jobs SET file_path = ? WHERE export_id = ? AND tenant_id = ?", (file_path, export_id, g.tenant_id)
    )
    db.commit()

    log_action("Export", "export_job", export_id, f"Exported {module} as {fmt}")
    return redirect(url_for("data_exchange.download_export", export_id=export_id))


@data_exchange_bp.route("/export/<int:export_id>/download")
@login_required
def download_export(export_id):
    db = get_db()
    job = db.execute(
        "SELECT * FROM export_jobs WHERE export_id = ? AND tenant_id = ?", (export_id, g.tenant_id)
    ).fetchone()
    if job is None or not job["file_path"] or not os.path.exists(job["file_path"]):
        abort(404)
    fmt = job["format"].lower()
    download_name = f"{job['module']}.{EXT[fmt]}"
    return send_file(job["file_path"], as_attachment=True, download_name=download_name, mimetype=MIME[fmt])


# =============================================================== IMPORT ===

def _decode_upload(file):
    """Decode an uploaded CSV's bytes to text, tolerating whatever encoding
    it was actually saved in — not just UTF-8. Excel's default "CSV (Comma
    delimited)" export uses the system codepage (Windows-1252 on most
    Windows installs); Sheets and most other tools use UTF-8, possibly with
    a BOM. Tries the common ones in order and falls back to Windows-1252
    read as "replace" (which never raises) rather than rejecting the upload
    outright."""
    raw = file.read()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1252", errors="replace")


def _normalize_row(row):
    """CSV headers arrive however the source file happened to capitalize
    them (e.g. 'NAME,TYPE'), and occasionally with doubled internal spaces
    from a sloppy export; the rest of this module works with lowercase,
    single-spaced keys."""
    return {re.sub(r"\s+", " ", (k or "").strip().lower()): (v or "").strip() for k, v in row.items()}


# Tokens a scraped/exported CSV uses to mark a cell the source didn't have,
# rather than just leaving it empty (an em dash is the common one from
# directory-style scrapes; the rest cover typical manual-export habits).
# Used by _resolve_org_row so e.g. a Website column full of "—" doesn't get
# imported and stored as if "—" were a real website.
_BLANK_PLACEHOLDERS = {"-", "--", "—", "–", "n/a", "na", "none", "null", "unknown"}


def _blank_placeholder(value):
    value = (value or "").strip()
    return "" if value.lower() in _BLANK_PLACEHOLDERS else value


def _normalize_phone_digits(raw):
    """Digits only, so '(650) 496-2220' and '650-496-2220' compare equal;
    an 11-digit number starting with '1' also drops that leading digit, so
    a US/Canada number entered with and without its country code still
    matches. Used only for the Contacts importer's same-person matching —
    nowhere that a phone number is actually stored keeps this stripped
    form."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


# ------------------------------------------------------------ import: contacts

# Header spellings this importer recognizes, mapped to the canonical field
# name the rest of this module (and batch_review.html) works with. Covers
# both a plain "full_name,email,phone,notes" file and a full
# Outlook/Exchange contacts export.
CONTACT_HEADER_ALIASES = {
    "title": ["title", "honorific"],
    "first_name": ["first name", "given name"],
    "last_name": ["last name", "surname", "family name"],
    "full_name": ["full_name", "full name", "name"],
    "suffix": ["suffix"],
    "organization": ["organization", "company", "company name"],
    "job_title": ["job title", "job_title", "position"],
    "street": ["street", "address", "street address"],
    "city": ["city"],
    "state": ["state", "province", "province/state"],
    "postal_code": ["business postal code", "postal code", "zip", "zip code"],
    "country": ["country"],
    "business_fax": ["business fax", "fax"],
    "business_phone": ["business phone", "work phone", "office phone"],
    "home_phone": ["home phone"],
    "home_phone_2": ["home phone 2", "home phone2"],
    "mobile_phone": ["mobile phone", "cell phone", "cell", "phone"],
    "categories": ["categories", "category"],
    "email": ["e-mail address", "email address", "email", "e-mail"],
    "email_3": ["e-mail 3 address", "email 3 address"],
    "web_page": ["web_page", "web page", "website", "url"],
    "date_of_birth": ["date_of_birth", "date of birth", "dob", "birthday"],
    "notes": ["notes", "note"],
}


def _resolve_contact_row(row):
    """Pulls the canonical fields out of a normalized CSV row by trying
    every known header spelling for each, then derives the fields the
    manual form always fills in but no single CSV column maps to directly
    (full_name, file_as, phone_entries, email_list, match_keys — a
    same-person signature used for duplicate detection instead of
    full_name alone, since a name is not a safe uniqueness key on its
    own)."""
    resolved = dict(row)
    for field, aliases in CONTACT_HEADER_ALIASES.items():
        value = ""
        for alias in aliases:
            if row.get(alias):
                value = row[alias]
                break
        resolved[field] = value

    first = resolved.get("first_name", "").strip()
    last = resolved.get("last_name", "").strip()
    full_name = resolved.get("full_name", "").strip()
    if not full_name:
        full_name = " ".join(p for p in (first, last) if p)
    resolved["full_name"] = full_name

    if first and last:
        resolved["file_as"] = f"{last}, {first}"
    else:
        resolved["file_as"] = last or first or ""

    phone_entries = []
    for col, phone_type in (
        ("business_phone", "Business"), ("home_phone", "Home"),
        ("home_phone_2", "Home"), ("mobile_phone", "Mobile"),
        ("business_fax", "Business Fax"),
    ):
        raw = (resolved.get(col) or "").strip()
        for number in [n.strip() for n in raw.split(";") if n.strip()]:
            phone_entries.append({"number": number, "phone_type": phone_type})
    resolved["phone_entries"] = phone_entries

    email_list = []
    for col in ("email", "email_3"):
        raw = (resolved.get(col) or "").strip()
        email_list.extend(e.strip() for e in raw.split(";") if e.strip())
    resolved["email_list"] = email_list

    match_keys = set()
    for e in email_list:
        match_keys.add(f"email:{e.lower()}")
    for entry in phone_entries:
        digits = _normalize_phone_digits(entry["number"])
        if len(digits) >= 7:
            match_keys.add(f"phone:{digits}")
    resolved["match_keys"] = sorted(match_keys)
    return resolved


def _resolve_geo_components(db, country_label, state_label, city_label):
    """Resolves a CSV row's separate Country / Province-State / City
    columns against the global geography lookups. A province/city that
    isn't seeded yet falls back to the free-text state_province_text/
    city_text columns, same convention used everywhere else a linked
    geography row might not exist."""
    country_row = match_country(db, country_label)
    country_id = country_row["country_id"] if country_row else None
    state_row = match_state(db, country_id, state_label) if country_id else None
    state_id = state_row["state_id"] if state_row else None
    city_row = match_city(db, state_id, city_label) if state_id else None
    city_id = city_row["city_id"] if city_row else None
    return {
        "country_id": country_id,
        "state_id": state_id,
        "state_text": None if state_id else ((state_label or "").strip() or None),
        "city_id": city_id,
        "city_text": None if city_id else ((city_label or "").strip() or None),
    }


def _resolve_contact_organization(db, name):
    """Find-or-create an Organization by name (case-insensitive,
    tenant-scoped) for a Contact's Organization column — a company named on
    the CSV that doesn't already exist is created bare (just a name; Type,
    address, phone etc. can be filled in afterward on its own page), rather
    than left unlinked or silently duplicated when a second row names the
    same company."""
    name = (name or "").strip()
    if not name:
        return None
    row = db.execute(
        "SELECT organization_id FROM organizations WHERE lower(organization_name) = lower(?) AND tenant_id = ?",
        (name, g.tenant_id),
    ).fetchone()
    if row:
        return row["organization_id"]
    db.execute(
        "INSERT INTO organizations (tenant_id, organization_name) VALUES (?, ?)",
        (g.tenant_id, name),
    )
    db.commit()
    row = db.execute(
        "SELECT organization_id FROM organizations WHERE lower(organization_name) = lower(?) AND tenant_id = ?",
        (name, g.tenant_id),
    ).fetchone()
    return row["organization_id"]


def _resolve_or_create_lookup(db, table, pk, label):
    """Look up a row in one of the small Contacts lookup tables
    (contact_titles / contact_suffixes / contact_categories) by label
    (case-insensitive), creating one — auto-generated code — the first
    time a new label is seen, so an import doesn't silently drop a
    Title/Suffix/Category that isn't one of the ones already seeded. Table
    Maintenance is where it can be relabeled, merged, or reordered
    afterward."""
    label = (label or "").strip()
    if not label:
        return None
    row = db.execute(
        f"SELECT {pk} FROM {table} WHERE lower(label) = lower(?) AND tenant_id = ?", (label, g.tenant_id)
    ).fetchone()
    if row:
        return row[pk]
    from seed_data import _slug

    base_code = _slug(label) or "OTHER"
    code = base_code
    attempt = 2
    while db.execute(f"SELECT 1 FROM {table} WHERE code = ? AND tenant_id = ?", (code, g.tenant_id)).fetchone():
        code = f"{base_code}_{attempt}"[:40]
        attempt += 1
    db.execute(
        f"""INSERT INTO {table} (tenant_id, code, label, sort_order, is_active)
            VALUES (?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {table} WHERE tenant_id = ?), 1)""",
        (g.tenant_id, code, label, g.tenant_id),
    )
    db.commit()
    row = db.execute(f"SELECT {pk} FROM {table} WHERE code = ? AND tenant_id = ?", (code, g.tenant_id)).fetchone()
    return row[pk]


@data_exchange_bp.route("/import/contacts", methods=["GET", "POST"])
@login_required
def import_contacts():
    db = get_db()
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Please choose a CSV file.", "error")
            return render_template("data_exchange/import_contacts_form.html")

        text = _decode_upload(file)
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for raw_row in reader:
            resolved = _resolve_contact_row(_normalize_row(raw_row))
            resolved["address"] = {
                "street": (resolved.get("street") or "").strip() or None,
                "postal_code": (resolved.get("postal_code") or "").strip() or None,
                **_resolve_geo_components(db, resolved.get("country", ""), resolved.get("state", ""), resolved.get("city", "")),
            }
            rows.append(resolved)
        if not rows:
            flash("That CSV had no rows.", "error")
            return render_template("data_exchange/import_contacts_form.html")

        db.execute(
            "INSERT INTO import_batches (tenant_id, source_type, target_module, file_name, status, row_count) VALUES (?, 'CSV', 'contacts', ?, 'Staged', ?)",
            (g.tenant_id, file.filename, len(rows)),
        )
        db.commit()
        batch_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]

        error_count = 0
        seen_by_name = {}
        for row in rows:
            full_name = (row.get("full_name") or "").strip()
            row_keys = set(row.get("match_keys") or [])
            if not full_name:
                status, errors = "Invalid", "A name is required (Full Name, or First/Last Name)"
            else:
                name_key = full_name.lower()
                prior_key_sets = seen_by_name.get(name_key, [])
                if row_keys and any(row_keys & prior for prior in prior_key_sets):
                    status, errors = "Invalid", "Duplicate contact within this file — same name and a matching phone/email as an earlier row"
                else:
                    status, errors = "Valid", None
                    seen_by_name.setdefault(name_key, []).append(row_keys)
            if status == "Invalid":
                error_count += 1
            db.execute(
                "INSERT INTO import_staging_rows (tenant_id, batch_id, raw_data, validation_status, validation_errors) VALUES (?, ?, ?, ?, ?)",
                (g.tenant_id, batch_id, json.dumps(row), status, errors),
            )
        db.execute(
            "UPDATE import_batches SET error_count = ?, status = 'Validated' WHERE batch_id = ? AND tenant_id = ?",
            (error_count, batch_id, g.tenant_id),
        )
        db.commit()
        log_action("Import", "import_batch", batch_id, f"Staged {len(rows)} rows from {file.filename} ({error_count} invalid)")
        return redirect(url_for("data_exchange.review_batch", batch_id=batch_id))

    return render_template("data_exchange/import_contacts_form.html")


# --------------------------------------------------------- import: organizations

# Labels for organization_type codes that don't already exist in
# organization_types — used only the first time a given code shows up in
# an import; after that it's just looked up.
ORG_TYPE_LABEL_OVERRIDES = {}


def _resolve_organization_type(db, code):
    """Look up an organization_types row by code, creating one (with a
    readable label) the first time a new code is seen. Table Maintenance >
    Organization Types is where the label can be tidied up afterward."""
    code = (code or "").strip().upper()
    if not code:
        return None
    row = db.execute(
        "SELECT organization_type_id FROM organization_types WHERE code = ? AND tenant_id = ?", (code, g.tenant_id)
    ).fetchone()
    if row:
        return row["organization_type_id"]
    label = ORG_TYPE_LABEL_OVERRIDES.get(code) or code.replace("_", " ").title()
    db.execute(
        """INSERT INTO organization_types (tenant_id, code, label, sort_order, is_active)
           VALUES (?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM organization_types WHERE tenant_id = ?), 1)""",
        (g.tenant_id, code, label, g.tenant_id),
    )
    db.commit()
    row = db.execute(
        "SELECT organization_type_id FROM organization_types WHERE code = ? AND tenant_id = ?", (code, g.tenant_id)
    ).fetchone()
    return row["organization_type_id"]


def _resolve_organization_domain(db, label):
    """Look up an organization_domains row by label, creating one the first
    time a new label is seen — same create-if-missing shape as
    _resolve_organization_type above, but keyed by a slugified code (via
    seed_data._slug, the exact same slug function seed_data.py's
    _seed_simple uses to seed this table) so a label matching an
    already-seeded domain — e.g. a CSV's "Automotive Services" — resolves
    to that existing row instead of creating a duplicate."""
    label = (label or "").strip()
    if not label:
        return None
    code = _slug(label)
    row = db.execute(
        "SELECT organization_domain_id FROM organization_domains WHERE code = ? AND tenant_id = ?", (code, g.tenant_id)
    ).fetchone()
    if row:
        return row["organization_domain_id"]
    db.execute(
        """INSERT INTO organization_domains (tenant_id, code, label, sort_order, is_active)
           VALUES (?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM organization_domains WHERE tenant_id = ?), 1)""",
        (g.tenant_id, code, label, g.tenant_id),
    )
    db.commit()
    row = db.execute(
        "SELECT organization_domain_id FROM organization_domains WHERE code = ? AND tenant_id = ?", (code, g.tenant_id)
    ).fetchone()
    return row["organization_domain_id"]


def _resolve_organization_subdomain(db, domain_id, label):
    """Same idea as _resolve_organization_domain, one level down. The code
    is prefixed with the parent domain's own code — matching seed_data.py's
    _seed_nested convention — because organization_subdomains.code is
    UNIQUE(tenant_id, code) across every domain, not just siblings under
    the same one, so two different domains could otherwise collide on a
    subdomain label as generic as, say, "Other"."""
    label = (label or "").strip()
    if not domain_id or not label:
        return None
    domain_row = db.execute(
        "SELECT code FROM organization_domains WHERE organization_domain_id = ? AND tenant_id = ?",
        (domain_id, g.tenant_id),
    ).fetchone()
    parent_code = (domain_row["code"] if domain_row else None) or str(domain_id)
    code = f"{parent_code}_{_slug(label)}"
    row = db.execute(
        "SELECT organization_subdomain_id FROM organization_subdomains WHERE code = ? AND tenant_id = ?",
        (code, g.tenant_id),
    ).fetchone()
    if row:
        return row["organization_subdomain_id"]
    db.execute(
        """INSERT INTO organization_subdomains (tenant_id, organization_domain_id, code, label, sort_order, is_active)
           VALUES (?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1 FROM organization_subdomains
                                 WHERE tenant_id = ? AND organization_domain_id = ?), 1)""",
        (g.tenant_id, domain_id, code, label, g.tenant_id, domain_id),
    )
    db.commit()
    row = db.execute(
        "SELECT organization_subdomain_id FROM organization_subdomains WHERE code = ? AND tenant_id = ?",
        (code, g.tenant_id),
    ).fetchone()
    return row["organization_subdomain_id"]


# Header spellings this importer recognizes, mapped to the canonical field
# name the rest of this module (and batch_review.html) works with. Lets
# real-world exports through without renaming columns first.
ORG_HEADER_ALIASES = {
    "name": ["name", "name of organization", "organization name", "organization", "org name"],
    "type": ["type", "category", "organization type"],
    "domain": ["domain", "organization domain"],
    "subdomain": ["sub-domain", "subdomain", "sub domain", "organization subdomain"],
    "address": ["address", "full address", "mailing address"],
    # street/city/state/postal_code feed organizations.street/city/state/
    # postal_code directly (the "Main Address" fields on the Organization
    # form) when the source file already has them split out -- more
    # reliable than re-parsing "address" as free text (see
    # _commit_organizations_rows). "address" above is unaffected either
    # way and keeps feeding the detailed, geography-matched
    # organization_addresses record as it always has.
    "street": ["street", "street address", "address line 1", "address1"],
    "city": ["city", "town"],
    "state": ["state", "province", "state/province", "province/state"],
    "postal_code": ["zip", "zip code", "postal code", "postal_code"],
    "phone": ["phone", "phone(s)", "phones", "telephone", "tel"],
    "email": ["email", "email(s)", "emails", "e-mail"],
    "website": ["website", "web", "url", "web site"],
    "primary_contact": ["primary contact(s)", "primary contact", "contact", "contacts"],
    "notes": ["notes", "description", "notes / what the organization does", "notes/description", "what the organization does"],
}


def _resolve_org_row(row):
    """Pulls the canonical fields (name/type/domain/subdomain/address/
    street/city/state/postal_code/phone/email/website/notes) out of a
    normalized CSV row by trying every known header spelling for each,
    treating a placeholder like "—" or "N/A" the same as a blank cell (see
    _blank_placeholder), and folds "Primary Contact(s)" into notes (there's
    no separate contact-person column on organizations)."""
    resolved = dict(row)
    for field, aliases in ORG_HEADER_ALIASES.items():
        value = ""
        for alias in aliases:
            candidate = _blank_placeholder(row.get(alias, ""))
            if candidate:
                value = candidate
                break
        resolved[field] = value

    notes = resolved.get("notes", "")
    contact = resolved.pop("primary_contact", "")
    if contact:
        notes = f"Primary Contact(s): {contact}" + (f"\n\n{notes}" if notes else "")
    resolved["notes"] = notes
    return resolved


def _lookup_id_by_label(db, table, pk, label):
    if not label:
        return None
    row = db.execute(f"SELECT {pk} FROM {table} WHERE lower(label) = lower(?) AND tenant_id = ?", (label, g.tenant_id)).fetchone()
    return row[pk] if row else None


@data_exchange_bp.route("/import/organizations", methods=["GET", "POST"])
@login_required
def import_organizations():
    db = get_db()
    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Please choose a CSV file.", "error")
            return render_template("data_exchange/import_organizations_form.html")

        text = _decode_upload(file)
        reader = csv.DictReader(io.StringIO(text))
        rows = []
        for raw_row in reader:
            resolved = _resolve_org_row(_normalize_row(raw_row))
            # Some source directories run one or more phone numbers straight
            # into the Address column with no field of their own — pulled
            # out here and, when there's no Phone column value already,
            # used to fill it in. The raw Address column itself
            # (resolved["address"] -> organizations.full_address) is left
            # exactly as given, since it's kept only as a legacy audit
            # trail.
            address_for_parsing, embedded_phones = extract_trailing_phones(resolved.get("address", ""))
            if embedded_phones and not (resolved.get("phone") or "").strip():
                resolved["phone"] = "; ".join(embedded_phones)
            resolved["address_parsed"] = parse_free_text_address(db, address_for_parsing)
            rows.append(resolved)
        if not rows:
            flash("That CSV had no rows.", "error")
            return render_template("data_exchange/import_organizations_form.html")

        db.execute(
            "INSERT INTO import_batches (tenant_id, source_type, target_module, file_name, status, row_count) VALUES (?, 'CSV', 'organizations', ?, 'Staged', ?)",
            (g.tenant_id, file.filename, len(rows)),
        )
        db.commit()
        batch_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]

        error_count = 0
        seen_names = set()
        for row in rows:
            name = (row.get("name") or "").strip()
            if not name:
                status, errors = "Invalid", "name is required"
            elif name.lower() in seen_names:
                status, errors = "Invalid", "Duplicate organization name within this file — already staged from an earlier row"
            else:
                status, errors = "Valid", None
                seen_names.add(name.lower())
            if status == "Invalid":
                error_count += 1
            db.execute(
                "INSERT INTO import_staging_rows (tenant_id, batch_id, raw_data, validation_status, validation_errors) VALUES (?, ?, ?, ?, ?)",
                (g.tenant_id, batch_id, json.dumps(row), status, errors),
            )
        db.execute(
            "UPDATE import_batches SET error_count = ?, status = 'Validated' WHERE batch_id = ? AND tenant_id = ?",
            (error_count, batch_id, g.tenant_id),
        )
        db.commit()
        log_action("Import", "import_batch", batch_id, f"Staged {len(rows)} rows from {file.filename} ({error_count} invalid)")
        return redirect(url_for("data_exchange.review_batch", batch_id=batch_id))

    return render_template("data_exchange/import_organizations_form.html")


# ------------------------------------------------------ import: business cards
#
# Unlike the CSV importers above (which stage every row for a batch review-
# and-commit cycle), a business card is a one-at-a-time, human-in-the-loop
# import: extract -> review/edit on screen -> save -- mirroring the Real
# Estate Agent reference app's flyer-photo import (ai_import.py /
# admin.import_listing_extract / import_listing_save). No import_batches
# row is created for these; each save is its own atomic upsert.

PENDING_CARD_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
PENDING_CARD_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def _pending_card_path(token, side, mime_type):
    """Path for one face of a pending (not-yet-saved) business-card photo,
    identified by the random token minted at extract time. Token is
    validated against the exact shape uuid4().hex always produces before
    it's allowed anywhere near a filesystem path, since (unlike front_mime/
    back_mime) it also arrives on the pending_card_image GET route as a
    plain URL segment from whatever the browser sends."""
    if not PENDING_CARD_TOKEN_RE.match(token or "") or side not in ("front", "back"):
        return None
    ext = PENDING_CARD_EXT.get(mime_type, "jpg")
    return os.path.join(Config.PENDING_CARDS_DIR, f"{token}_{side}.{ext}")


def _save_pending_card_image(token, side, image_bytes, mime_type):
    path = _pending_card_path(token, side, mime_type)
    with open(path, "wb") as f:
        f.write(image_bytes)


def _cleanup_stale_pending_cards(max_age_seconds=6 * 3600):
    """Best-effort sweep of abandoned pending-card temp files -- an extract
    that's never saved (the person navigates away, or re-extracts instead)
    would otherwise leave its image file(s) here forever, since this app
    has no background worker to run a real scheduled cleanup. Runs
    opportunistically on each new extract instead."""
    try:
        now = time.time()
        for name in os.listdir(Config.PENDING_CARDS_DIR):
            path = os.path.join(Config.PENDING_CARDS_DIR, name)
            try:
                if now - os.path.getmtime(path) > max_age_seconds:
                    os.remove(path)
            except OSError:
                pass
    except OSError:
        pass


def _promote_pending_card_image(pending_path):
    """Moves a validated pending-card temp file into the permanent Contacts
    uploads directory under a fresh random filename -- same naming
    convention blueprints.contacts._save_image_upload uses -- once a Save
    has actually happened. Returns the stored filename (not the full path),
    same return shape _save_image_upload uses."""
    ext = pending_path.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.replace(pending_path, os.path.join(Config.UPLOADS_DIR, filename))
    return filename


def _find_organization_by_name(db, name):
    name = (name or "").strip()
    if not name:
        return None
    return db.execute(
        "SELECT * FROM organizations WHERE lower(organization_name) = lower(?) AND tenant_id = ?",
        (name, g.tenant_id),
    ).fetchone()


def _find_contact_for_card(db, emails, full_name, organization_id):
    """Match priority for a card's named person against existing Contacts:
    (1) any extracted email matching an existing contact_emails row --
    the most reliable identifier a card can offer. (2) failing that, a
    full_name match, but ONLY among contacts already linked to the same
    resolved Organization -- a bare name match with nothing to anchor it
    is too weak on its own (there's more than one "John Smith"), so
    without a resolved organization_id a name alone never matches and a
    new contact is created instead."""
    for email in emails or []:
        email = (email or "").strip()
        if not email:
            continue
        row = db.execute(
            """SELECT c.* FROM contacts c JOIN contact_emails ce ON ce.contact_id = c.contact_id
               WHERE lower(ce.email_address) = lower(?) AND c.tenant_id = ? AND c.is_deleted = 0""",
            (email, g.tenant_id),
        ).fetchone()
        if row:
            return row
    full_name = (full_name or "").strip()
    if full_name and organization_id:
        row = db.execute(
            """SELECT * FROM contacts WHERE lower(full_name) = lower(?) AND current_organization_id = ?
               AND tenant_id = ? AND is_deleted = 0""",
            (full_name, organization_id, g.tenant_id),
        ).fetchone()
        if row:
            return row
    return None


def _apply_organization_from_card(db, data, existing_org_row):
    """Create or update an Organization from extracted business-card data.
    An existing match only ever has its currently-EMPTY fields filled in:
    website is set only if organizations.website is blank; a phone, email,
    or address is added only if nothing matching is already on file
    (checked by normalized value / exact address-presence, so re-scanning
    the same card twice doesn't pile up duplicates or overwrite anything
    already recorded). Returns (organization_id, created_bool)."""
    name = (data.get("organization_name") or "").strip()

    if existing_org_row:
        org_id = existing_org_row["organization_id"]
        created = False
        website = (data.get("organization_website") or "").strip()
        if website and not (existing_org_row["website"] or "").strip():
            db.execute(
                "UPDATE organizations SET website = ?, updated_at = datetime('now') WHERE organization_id = ? AND tenant_id = ?",
                (website, org_id, g.tenant_id),
            )
    else:
        if not name:
            return None, False
        db.execute(
            "INSERT INTO organizations (tenant_id, organization_name, website) VALUES (?, ?, ?)",
            (g.tenant_id, name, (data.get("organization_website") or "").strip() or None),
        )
        db.commit()
        org_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        created = True

    phone = (data.get("organization_phone") or "").strip()
    if phone:
        digits = _normalize_phone_digits(phone)
        already_have = any(
            digits and _normalize_phone_digits(row["number"]) == digits
            for row in db.execute("SELECT number FROM organization_phones WHERE organization_id = ?", (org_id,))
        )
        if not already_have:
            type_id = _lookup_id_by_label(db, "organization_phone_types", "phone_type_id", _classify_org_phone_label(data.get("organization_phone_label")))
            has_any_phone = db.execute("SELECT 1 FROM organization_phones WHERE organization_id = ?", (org_id,)).fetchone()
            db.execute(
                "INSERT INTO organization_phones (tenant_id, organization_id, phone_type_id, number, is_primary) VALUES (?, ?, ?, ?, ?)",
                (g.tenant_id, org_id, type_id, phone, 0 if has_any_phone else 1),
            )

    email = (data.get("organization_email") or "").strip()
    if email:
        already_have = db.execute(
            "SELECT 1 FROM organization_emails WHERE organization_id = ? AND lower(email_address) = lower(?)", (org_id, email)
        ).fetchone()
        if not already_have:
            has_any_email = db.execute("SELECT 1 FROM organization_emails WHERE organization_id = ?", (org_id,)).fetchone()
            db.execute(
                "INSERT INTO organization_emails (tenant_id, organization_id, email_address, is_primary) VALUES (?, ?, ?, ?)",
                (g.tenant_id, org_id, email, 0 if has_any_email else 1),
            )

    street = (data.get("address_street") or "").strip()
    city = (data.get("address_city") or "").strip()
    if street or city:
        has_address = db.execute("SELECT 1 FROM organization_addresses WHERE organization_id = ?", (org_id,)).fetchone()
        if not has_address:
            geo = _resolve_geo_components(db, data.get("address_country", ""), data.get("address_state", ""), data.get("address_city", ""))
            db.execute(
                """INSERT INTO organization_addresses
                   (tenant_id, organization_id, street, unit, country_id, state_id, state_province_text,
                    city_id, city_text, postal_code, is_primary)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    g.tenant_id, org_id, street or None, (data.get("address_unit") or "").strip() or None,
                    geo["country_id"], geo["state_id"], geo["state_text"], geo["city_id"], geo["city_text"],
                    (data.get("address_postal_code") or "").strip() or None,
                ),
            )

    db.commit()
    return org_id, created


def _apply_contact_from_card(db, contact_data, organization_id, front_filename, back_filename):
    """Create or update a Contact from one extracted business-card contact
    entry. An existing match (see _find_contact_for_card) only has its
    empty fields filled in -- job title and organization link are set only
    if currently blank; a phone/email/address already on file is never
    touched, only added to if the card shows something not already
    recorded. Card images always replace whatever was on file, since
    capturing the card image is the point of this import (same
    replace-on-upload behavior as the contact edit form). Returns
    (contact_id, created_bool)."""
    full_name = (contact_data.get("full_name") or "").strip()
    emails = [e.strip() for e in (contact_data.get("emails") or []) if (e or "").strip()]
    existing = _find_contact_for_card(db, emails, full_name, organization_id)

    if existing:
        contact_id = existing["contact_id"]
        created = False
        updates, params = [], []
        if organization_id and not existing["current_organization_id"]:
            updates.append("current_organization_id = ?")
            params.append(organization_id)
        job_title = (contact_data.get("job_title") or "").strip()
        if job_title and not (existing["current_job_title"] or "").strip():
            updates.append("current_job_title = ?")
            params.append(job_title)
        if updates:
            params += [contact_id, g.tenant_id]
            db.execute(f"UPDATE contacts SET {', '.join(updates)}, updated_at = datetime('now') WHERE contact_id = ? AND tenant_id = ?", params)
    else:
        if not full_name:
            return None, False
        db.execute(
            "INSERT INTO contacts (tenant_id, full_name, current_organization_id, current_job_title) VALUES (?, ?, ?, ?)",
            (g.tenant_id, full_name, organization_id, (contact_data.get("job_title") or "").strip() or None),
        )
        db.commit()
        contact_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        created = True

    for email in emails:
        already_have = db.execute(
            "SELECT 1 FROM contact_emails WHERE contact_id = ? AND lower(email_address) = lower(?)", (contact_id, email)
        ).fetchone()
        if not already_have:
            has_any = db.execute("SELECT 1 FROM contact_emails WHERE contact_id = ?", (contact_id,)).fetchone()
            db.execute(
                "INSERT INTO contact_emails (tenant_id, contact_id, email_address, is_primary) VALUES (?, ?, ?, ?)",
                (g.tenant_id, contact_id, email, 0 if has_any else 1),
            )

    for entry in (contact_data.get("phones") or []):
        number = (entry.get("number") or "").strip()
        if not number:
            continue
        digits = _normalize_phone_digits(number)
        already_have = any(
            digits and _normalize_phone_digits(row["number"]) == digits
            for row in db.execute("SELECT number FROM contact_phones WHERE contact_id = ?", (contact_id,))
        )
        if already_have:
            continue
        has_any = db.execute("SELECT 1 FROM contact_phones WHERE contact_id = ?", (contact_id,)).fetchone()
        db.execute(
            "INSERT INTO contact_phones (tenant_id, contact_id, phone_type, number, is_primary) VALUES (?, ?, ?, ?, ?)",
            (g.tenant_id, contact_id, _classify_contact_phone_label(entry.get("label")), number, 0 if has_any else 1),
        )

    addr = contact_data.get("_shared_address") or {}
    if (addr.get("street") or "").strip() or (addr.get("city") or "").strip():
        has_address = db.execute("SELECT 1 FROM addresses WHERE owner_type='Contact' AND owner_id = ?", (contact_id,)).fetchone()
        if not has_address:
            geo = _resolve_geo_components(db, addr.get("country", ""), addr.get("state", ""), addr.get("city", ""))
            db.execute(
                """INSERT INTO addresses (tenant_id, owner_type, owner_id, address_type, street, unit,
                   country_id, state_id, state_province_text, city_id, city_text, postal_code, is_primary)
                   VALUES (?, 'Contact', ?, 'Business', ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    g.tenant_id, contact_id, (addr.get("street") or "").strip() or None, (addr.get("unit") or "").strip() or None,
                    geo["country_id"], geo["state_id"], geo["state_text"], geo["city_id"], geo["city_text"],
                    (addr.get("postal_code") or "").strip() or None,
                ),
            )

    if front_filename or back_filename:
        old = db.execute(
            "SELECT business_card_front_path, business_card_back_path FROM contacts WHERE contact_id = ?", (contact_id,)
        ).fetchone()
        if front_filename and old["business_card_front_path"]:
            _delete_image_upload(old["business_card_front_path"])
        if back_filename and old["business_card_back_path"]:
            _delete_image_upload(old["business_card_back_path"])
        db.execute(
            "UPDATE contacts SET business_card_front_path = COALESCE(?, business_card_front_path), "
            "business_card_back_path = COALESCE(?, business_card_back_path) WHERE contact_id = ? AND tenant_id = ?",
            (front_filename, back_filename, contact_id, g.tenant_id),
        )

    db.commit()
    return contact_id, created


@data_exchange_bp.route("/import/business-card", methods=["GET"])
@login_required
@agent_access_required("business_card_import")
def import_business_card_form():
    return render_template("data_exchange/import_business_card_form.html")


@data_exchange_bp.route("/import/business-card/extract", methods=["POST"])
@login_required
@agent_access_required("business_card_import")
def import_business_card_extract():
    front = request.files.get("front_image")
    back = request.files.get("back_image")
    if not front or not front.filename:
        flash("Please choose a front-of-card image.", "error")
        return render_template("data_exchange/import_business_card_form.html")

    front_bytes = front.read()
    front_mime = front.mimetype or "image/jpeg"
    has_back = bool(back and back.filename)
    back_bytes = back.read() if has_back else None
    back_mime = (back.mimetype or "image/jpeg") if has_back else None

    try:
        data, usage = extract_business_card(front_bytes, front_mime, back_bytes, back_mime)
    except ExtractionError as e:
        flash(str(e), "error")
        return render_template("data_exchange/import_business_card_form.html")

    db = get_db()
    existing_org = _find_organization_by_name(db, data.get("organization_name"))
    shared_address = {
        "street": data.get("address_street") or "",
        "unit": data.get("address_unit") or "",
        "city": data.get("address_city") or "",
        "state": data.get("address_state") or "",
        "postal_code": data.get("address_postal_code") or "",
        "country": data.get("address_country") or "",
    }

    contacts_preview = []
    for c in data.get("contacts") or []:
        emails = [e.strip() for e in (c.get("emails") or []) if (e or "").strip()]
        existing_contact = _find_contact_for_card(
            db, emails, c.get("full_name"), existing_org["organization_id"] if existing_org else None
        )
        contacts_preview.append({"data": c, "existing": existing_contact})
    if not contacts_preview:
        # Still let the person review/save the Organization info and add a
        # contact by hand on the review screen, rather than dead-ending here.
        contacts_preview.append({"data": {"full_name": "", "job_title": "", "emails": [], "phones": []}, "existing": None})

    # The photo(s) are held here, keyed by a random token, until Save -- see
    # the module docstring above for why (Werkzeug's 500KB cap on a non-file
    # form field rules out carrying the actual image bytes through the
    # review form as base64, the way the Real Estate Agent reference app's
    # photo_b64 hidden field does for its much smaller flyer photos).
    _cleanup_stale_pending_cards()
    card_token = uuid.uuid4().hex
    _save_pending_card_image(card_token, "front", front_bytes, front_mime)
    if back_bytes:
        _save_pending_card_image(card_token, "back", back_bytes, back_mime)

    log_action(
        "Import", "business_card", None,
        f"Extracted business card ({data.get('organization_name') or 'no company read'})",
    )
    log_agent_usage(g.tenant_id, "business_card_import", user_id=g.user_id,
                    detail=data.get("organization_name") or "no company read",
                    model_code=usage["model_code"], tokens_input=usage["tokens_input"], tokens_output=usage["tokens_output"])
    return render_template(
        "data_exchange/import_business_card_review.html",
        data=data, existing_org=existing_org, contacts=contacts_preview, shared_address=shared_address,
        card_token=card_token, front_mime=front_mime, back_mime=(back_mime if back_bytes else None),
        contact_phone_types=CONTACT_PHONE_TYPES,
    )


@data_exchange_bp.route("/import/business-card/pending/<token>/<side>")
@login_required
def pending_card_image(token, side):
    """Serves one face of a not-yet-saved card photo for the review page's
    <img> preview, straight from the pending-cards holding directory (see
    config.py's PENDING_CARDS_DIR) -- the review form itself only carries
    the token, not the image bytes (see import_business_card_extract)."""
    mime_type = request.args.get("mime") or "image/jpeg"
    path = _pending_card_path(token, side, mime_type)
    if not path or not os.path.exists(path):
        abort(404)
    directory, filename = os.path.split(path)
    return send_from_directory(directory, filename)


@data_exchange_bp.route("/import/business-card/save", methods=["POST"])
@login_required
def import_business_card_save():
    db = get_db()
    form = request.form

    org_data = {k: form.get(k, "").strip() for k in (
        "organization_name", "organization_website", "organization_phone", "organization_phone_label",
        "organization_email", "address_street", "address_unit", "address_city", "address_state",
        "address_postal_code", "address_country",
    )}

    existing_org_row = None
    existing_org_id = form.get("existing_organization_id") or None
    if existing_org_id:
        existing_org_row = db.execute(
            "SELECT * FROM organizations WHERE organization_id = ? AND tenant_id = ?", (existing_org_id, g.tenant_id)
        ).fetchone()
    if not existing_org_row and org_data["organization_name"]:
        existing_org_row = _find_organization_by_name(db, org_data["organization_name"])

    organization_id = None
    if org_data["organization_name"] or existing_org_row:
        organization_id, _org_created = _apply_organization_from_card(db, org_data, existing_org_row)

    # The card images move from the pending-cards holding directory into the
    # permanent Contacts uploads directory only now, at Save -- see
    # config.py's PENDING_CARDS_DIR and import_business_card_extract above.
    # If the token/mime don't resolve to a file that still exists (e.g. this
    # form was already submitted once, or the pending copy aged out), that
    # image is simply not attached rather than erroring the whole save.
    card_token = form.get("card_token") or ""
    front_pending = _pending_card_path(card_token, "front", form.get("front_mime") or "image/jpeg")
    back_pending = _pending_card_path(card_token, "back", form.get("back_mime") or "image/jpeg") if form.get("back_mime") else None
    front_filename = _promote_pending_card_image(front_pending) if front_pending and os.path.exists(front_pending) else None
    back_filename = _promote_pending_card_image(back_pending) if back_pending and os.path.exists(back_pending) else None

    shared_address = {
        "street": org_data["address_street"], "unit": org_data["address_unit"], "city": org_data["address_city"],
        "state": org_data["address_state"], "postal_code": org_data["address_postal_code"], "country": org_data["address_country"],
    }

    saved = []
    contact_count = int(form.get("contact_count") or 0)
    for i in range(contact_count):
        prefix = f"contact-{i}-"
        full_name = form.get(prefix + "full_name", "").strip()
        if not full_name:
            continue
        phones = []
        for j in (1, 2, 3):
            number = form.get(f"{prefix}phone{j}_number", "").strip()
            if number:
                phones.append({"number": number, "label": form.get(f"{prefix}phone{j}_label", "")})
        contact_data = {
            "full_name": full_name,
            "job_title": form.get(prefix + "job_title", "").strip(),
            "emails": [e.strip() for e in re.split(r"[,\n]", form.get(prefix + "emails", "")) if e.strip()],
            "phones": phones,
            "_shared_address": shared_address,
        }
        # The one physical card photo is linked to the first (primary)
        # contact only -- a card almost always names one person; on the
        # rare two-name card there's still just one image to attach.
        contact_id, created = _apply_contact_from_card(
            db, contact_data, organization_id, front_filename if i == 0 else None, back_filename if i == 0 else None,
        )
        if contact_id:
            saved.append((contact_id, created))

    if not saved:
        flash("No contact name was given, so nothing was saved — a business card import always needs at least one named person.", "error")
        return redirect(url_for("data_exchange.import_business_card_form"))

    log_action("Import", "business_card", saved[0][0], f"Saved business card import ({len(saved)} contact(s), org {organization_id})")
    new_count = sum(1 for _, created in saved if created)
    flash(f"Saved {len(saved)} contact(s) from business card ({new_count} new, {len(saved) - new_count} matched to an existing contact).", "success")
    return redirect(url_for("contacts.view_contact", contact_id=saved[0][0]))


# --------------------------------------------------------- import ads/flyers
#
# Mass import for photos of ads/flyers collected before their advertiser is
# necessarily in GSS at all yet — unlike organizations.py's per-Organization
# Ad import (which assumes the org already exists, since the upload happens
# from that org's own page), a photo here might be the very FIRST record of
# a business the tenant has never entered. So each extracted ad also
# identifies its advertiser (ad_import.extract_ads_for_import, a separate
# extraction from the org-already-known extract_ads_from_image the
# per-Organization feature keeps using unchanged) and, unlike that feature,
# goes through a staged review (import_batches/import_staging_rows, the same
# batch machinery the CSV importers use) before anything is written — a scan
# that misreads a business name would otherwise silently create a bad
# Organization record, which is a bigger mistake to make silently than a
# misread phone number on an already-known org's ad. The Ad Listing itself
# is still built with organizations.py's own unchanged helpers
# (_ad_dict_from_extracted/_create_ad_listing/etc.) — see _commit_ads_rows
# below — so "the existing ads/flyers structure in the organization form"
# really is the same structure, just fed from a different starting point.


def _apply_contact_from_ad_data(db, data, organization_id):
    """Create or find a Contact from an ad/flyer's named contact_name/
    contact_phone/contact_email (see ad_import.extract_ads_for_import) — a
    lighter-weight sibling of _apply_contact_from_card above, since an ad
    names at most one person with at most one phone/email each, not a
    business card's full shape (job title, multiple phones, a card image).
    Match/create semantics otherwise mirror _apply_contact_from_card:
    reused via _find_contact_for_card, only empty fields filled in on a
    match, phone/email added only if not already on file. Returns
    contact_id, or None if the ad named no specific person."""
    full_name = (data.get("contact_name") or "").strip()
    if not full_name:
        return None
    email = (data.get("contact_email") or "").strip()
    existing = _find_contact_for_card(db, [email] if email else [], full_name, organization_id)

    if existing:
        contact_id = existing["contact_id"]
        if organization_id and not existing["current_organization_id"]:
            db.execute(
                "UPDATE contacts SET current_organization_id = ?, updated_at = datetime('now') WHERE contact_id = ? AND tenant_id = ?",
                (organization_id, contact_id, g.tenant_id),
            )
    else:
        db.execute(
            "INSERT INTO contacts (tenant_id, full_name, current_organization_id) VALUES (?, ?, ?)",
            (g.tenant_id, full_name, organization_id),
        )
        db.commit()
        contact_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]

    if email:
        already_have = db.execute(
            "SELECT 1 FROM contact_emails WHERE contact_id = ? AND lower(email_address) = lower(?)", (contact_id, email)
        ).fetchone()
        if not already_have:
            has_any = db.execute("SELECT 1 FROM contact_emails WHERE contact_id = ?", (contact_id,)).fetchone()
            db.execute(
                "INSERT INTO contact_emails (tenant_id, contact_id, email_address, is_primary) VALUES (?, ?, ?, ?)",
                (g.tenant_id, contact_id, email, 0 if has_any else 1),
            )

    phone = (data.get("contact_phone") or "").strip()
    if phone:
        digits = _normalize_phone_digits(phone)
        already_have = any(
            digits and _normalize_phone_digits(row["number"]) == digits
            for row in db.execute("SELECT number FROM contact_phones WHERE contact_id = ?", (contact_id,))
        )
        if not already_have:
            has_any = db.execute("SELECT 1 FROM contact_phones WHERE contact_id = ?", (contact_id,)).fetchone()
            db.execute(
                "INSERT INTO contact_phones (tenant_id, contact_id, phone_type, number, is_primary) VALUES (?, ?, ?, ?, ?)",
                (g.tenant_id, contact_id, "Business", phone, 0 if has_any else 1),
            )

    db.commit()
    return contact_id


@data_exchange_bp.route("/import/ads-flyers", methods=["GET"])
@login_required
@agent_access_required("ad_import")
def import_ads_flyers_form():
    return render_template("data_exchange/import_ads_flyers_form.html", max_batch_images=MAX_BATCH_AD_IMAGES)


@data_exchange_bp.route("/import/ads-flyers/extract", methods=["POST"])
@login_required
@agent_access_required("ad_import")
def import_ads_flyers_extract():
    db = get_db()
    zip_file = request.files.get("zip_file")
    image_files = [f for f in request.files.getlist("images") if f and f.filename]

    images = []  # (filename, image_bytes, mime_type)
    if zip_file and zip_file.filename:
        try:
            images.extend(iter_images_from_zip(zip_file.read()))
        except zipfile.BadZipFile:
            flash("That file isn't a valid zip archive.", "error")
            return redirect(url_for("data_exchange.import_ads_flyers_form"))
    for f in image_files:
        images.append((f.filename, f.read(), f.mimetype or "image/jpeg"))

    if not images:
        flash("Choose a zip file of ad/flyer photos, or select one or more image files.", "error")
        return redirect(url_for("data_exchange.import_ads_flyers_form"))

    if len(images) > MAX_BATCH_AD_IMAGES:
        flash(
            f"That's {len(images)} images — the limit per batch is {MAX_BATCH_AD_IMAGES}. Split it into smaller batches.",
            "error",
        )
        return redirect(url_for("data_exchange.import_ads_flyers_form"))

    _cleanup_stale_pending_ads()

    batch_name = zip_file.filename if (zip_file and zip_file.filename) else f"{len(images)} image file(s)"
    db.execute(
        "INSERT INTO import_batches (tenant_id, source_type, target_module, file_name, status, row_count) "
        "VALUES (?, 'JSON', 'ads', ?, 'Staged', 0)",
        (g.tenant_id, batch_name),
    )
    batch_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]

    row_count = 0
    error_count = 0
    for filename, image_bytes, mime_type in images:
        try:
            ads, usage = extract_ads_for_import(image_bytes, mime_type)
        except AdExtractionError as e:
            error_count += 1
            db.execute(
                "INSERT INTO import_staging_rows (tenant_id, batch_id, raw_data, validation_status, validation_errors) "
                "VALUES (?, ?, ?, 'Invalid', ?)",
                (g.tenant_id, batch_id, json.dumps({"_source_filename": filename}), f"Couldn't read this image: {e}"),
            )
            continue

        log_agent_usage(g.tenant_id, "ad_import", user_id=g.user_id, detail=filename,
                        model_code=usage["model_code"], tokens_input=usage["tokens_input"], tokens_output=usage["tokens_output"])

        # One photo can hold more than one distinct ad (see
        # ad_import.extract_ads_for_import) — saved once here, referenced
        # by every ad row it produced via _photo_token, promoted to
        # permanent storage at most once per token at commit time.
        ad_token = uuid.uuid4().hex
        _save_pending_ad_image(ad_token, image_bytes, mime_type)

        for item in ads:
            org_name = (item.get("organization_name") or "").strip()
            existing_org = _find_organization_by_name(db, org_name) if org_name else None
            contact_name = (item.get("contact_name") or "").strip()
            existing_contact = None
            if contact_name:
                email = (item.get("contact_email") or "").strip()
                existing_contact = _find_contact_for_card(
                    db, [email] if email else [], contact_name,
                    existing_org["organization_id"] if existing_org else None,
                )

            row_data = dict(item)
            row_data["_photo_token"] = ad_token
            row_data["_photo_mime"] = mime_type
            row_data["_source_filename"] = filename
            row_data["_existing_org_id"] = existing_org["organization_id"] if existing_org else None
            row_data["_existing_org_name"] = existing_org["organization_name"] if existing_org else None
            row_data["_existing_contact_id"] = existing_contact["contact_id"] if existing_contact else None
            row_data["_existing_contact_name"] = existing_contact["full_name"] if existing_contact else None

            if org_name:
                status, errors = "Valid", None
            else:
                status, errors = (
                    "Invalid",
                    "No business/organization name could be read from this ad — it can't be imported without one.",
                )

            db.execute(
                "INSERT INTO import_staging_rows (tenant_id, batch_id, raw_data, validation_status, validation_errors) "
                "VALUES (?, ?, ?, ?, ?)",
                (g.tenant_id, batch_id, json.dumps(row_data), status, errors),
            )
            row_count += 1
            if status == "Invalid":
                error_count += 1

    db.execute(
        "UPDATE import_batches SET row_count = ?, error_count = ?, status = 'Validated' WHERE batch_id = ? AND tenant_id = ?",
        (row_count, error_count, batch_id, g.tenant_id),
    )
    db.commit()
    log_action("Import", "ads_flyers_batch", batch_id, f"Extracted {row_count} ad(s) from {len(images)} image(s)")
    flash(f"Extracted {row_count} ad(s) from {len(images)} image(s) — review before committing.", "success")
    return redirect(url_for("data_exchange.review_batch", batch_id=batch_id))


@data_exchange_bp.route("/import/ads-flyers/pending/<token>")
@login_required
def pending_ad_flyer_image(token):
    """Serves a not-yet-committed ad/flyer photo for the batch review
    page's thumbnail — straight from the same pending-ads holding
    directory organizations.py's single-ad import uses (_pending_ad_path
    validates the token before it's allowed anywhere near a filesystem
    path)."""
    mime_type = request.args.get("mime") or "image/jpeg"
    path = _pending_ad_path(token, mime_type)
    if not path or not os.path.exists(path):
        abort(404)
    directory, filename = os.path.split(path)
    return send_from_directory(directory, filename)


# ------------------------------------------------------------------- review

@data_exchange_bp.route("/import/batches/<int:batch_id>")
@login_required
def review_batch(batch_id):
    db = get_db()
    batch = db.execute(
        "SELECT * FROM import_batches WHERE batch_id = ? AND tenant_id = ?", (batch_id, g.tenant_id)
    ).fetchone()
    if batch is None:
        abort(404)
    rows = db.execute("SELECT * FROM import_staging_rows WHERE batch_id = ? ORDER BY staging_id", (batch_id,)).fetchall()
    parsed = [dict(r, parsed=json.loads(r["raw_data"])) for r in rows]
    return render_template("data_exchange/batch_review.html", batch=batch, rows=parsed)


def _find_matching_contact(db, full_name, match_keys):
    """Same-name-plus-shared-phone/email reuse check for the Contacts
    importer — a person's name just isn't a reliable identifier the way a
    company name usually is. Only a name match that ALSO shares a
    normalized phone or email with an existing contact is reused; a
    same-named contact with no overlapping contact info is left alone and
    a new contact is created instead."""
    if not match_keys:
        return None
    candidates = db.execute(
        "SELECT contact_id FROM contacts WHERE lower(full_name) = lower(?) AND tenant_id = ? AND is_deleted = 0",
        (full_name, g.tenant_id),
    ).fetchall()
    for cand in candidates:
        cand_keys = set()
        for row in db.execute("SELECT email_address FROM contact_emails WHERE contact_id = ?", (cand["contact_id"],)):
            cand_keys.add(f"email:{row['email_address'].strip().lower()}")
        for row in db.execute("SELECT number FROM contact_phones WHERE contact_id = ?", (cand["contact_id"],)):
            digits = _normalize_phone_digits(row["number"])
            if len(digits) >= 7:
                cand_keys.add(f"phone:{digits}")
        if match_keys & cand_keys:
            return cand["contact_id"]
    return None


def _commit_contacts_rows(db, rows):
    """Commit staged contact rows. A row is reused rather than duplicated
    only when an existing contact shares BOTH its name and a phone/email
    (see _find_matching_contact) — so re-running this import doesn't pile
    up duplicates of what already committed cleanly, without ever
    collapsing two different people who happen to share a name into one
    contact."""
    committed = 0
    for r in rows:
        data = json.loads(r["raw_data"])
        full_name = (data.get("full_name") or "").strip()
        match_keys = set(data.get("match_keys") or [])

        existing_id = _find_matching_contact(db, full_name, match_keys)
        if existing_id:
            contact_id = existing_id
        else:
            title_id = _resolve_or_create_lookup(db, "contact_titles", "contact_title_id", data.get("title"))
            suffix_id = _resolve_or_create_lookup(db, "contact_suffixes", "contact_suffix_id", data.get("suffix"))
            org_id = _resolve_contact_organization(db, data.get("organization"))

            categories_raw = (data.get("categories") or "").strip()
            first_category = categories_raw.split(";")[0].strip() if categories_raw else ""
            category_id = _resolve_or_create_lookup(db, "contact_categories", "contact_category_id", first_category)

            notes_parts = []
            if categories_raw:
                notes_parts.append(f"Categories: {categories_raw}")
            source_notes = (data.get("notes") or "").strip()
            if source_notes:
                notes_parts.append(source_notes)

            db.execute(
                """INSERT INTO contacts
                   (tenant_id, title_id, full_name, suffix_id, file_as, current_organization_id,
                    current_job_title, contact_category_id, web_page, date_of_birth, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    g.tenant_id, title_id, full_name, suffix_id,
                    (data.get("file_as") or "").strip() or None, org_id,
                    (data.get("job_title") or "").strip() or None, category_id,
                    (data.get("web_page") or "").strip() or None, (data.get("date_of_birth") or "").strip() or None,
                    ("\n\n".join(notes_parts) or None),
                ),
            )
            contact_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]

            for i, addr_value in enumerate(data.get("email_list") or []):
                db.execute(
                    "INSERT INTO contact_emails (tenant_id, contact_id, email_address, is_primary) VALUES (?, ?, ?, ?)",
                    (g.tenant_id, contact_id, addr_value, 1 if i == 0 else 0),
                )

            for i, entry in enumerate(data.get("phone_entries") or []):
                db.execute(
                    "INSERT INTO contact_phones (tenant_id, contact_id, phone_type, number, is_primary) VALUES (?, ?, ?, ?, ?)",
                    (g.tenant_id, contact_id, entry["phone_type"], entry["number"], 1 if i == 0 else 0),
                )

            addr = data.get("address") or {}
            if addr.get("street") or addr.get("postal_code") or addr.get("country_id") \
                    or addr.get("state_id") or addr.get("state_text") or addr.get("city_id") or addr.get("city_text"):
                db.execute(
                    """INSERT INTO addresses
                       (tenant_id, owner_type, owner_id, address_type, street, region_id, country_id,
                        state_id, state_province_text, city_id, city_text, postal_code, is_primary)
                       VALUES (?, 'Contact', ?, 'Business', ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (
                        g.tenant_id, contact_id, addr.get("street"), addr.get("region_id"), addr.get("country_id"),
                        addr.get("state_id"), addr.get("state_text"), addr.get("city_id"), addr.get("city_text"),
                        addr.get("postal_code"),
                    ),
                )

        db.execute(
            "UPDATE import_staging_rows SET committed_entity_id = ? WHERE staging_id = ? AND tenant_id = ?",
            (contact_id, r["staging_id"], g.tenant_id),
        )
        committed += 1
    return committed


def _commit_organizations_rows(db, rows):
    """Commit staged organization rows. A name that already exists in the
    live organizations table (case-insensitive) is reused rather than
    duplicated — the staging row is still marked committed, pointing at
    the existing record. Address/phone/email/website/notes/domain/
    subdomain/Main-Address fields are only written on the INSERT path (a
    brand-new organization); an existing organization that's matched by
    name is left as-is."""
    committed = 0
    mailing_address_type_id = _lookup_id_by_label(db, "organization_address_types", "address_type_id", "Mailing Address")
    office_phone_type_id = _lookup_id_by_label(db, "organization_phone_types", "phone_type_id", "Office")
    for r in rows:
        data = json.loads(r["raw_data"])
        name = (data.get("name") or "").strip()

        existing = db.execute(
            "SELECT organization_id FROM organizations WHERE lower(organization_name) = lower(?) AND tenant_id = ?",
            (name, g.tenant_id),
        ).fetchone()
        if existing:
            org_id = existing["organization_id"]
        else:
            type_id = _resolve_organization_type(db, data.get("type"))
            domain_id = _resolve_organization_domain(db, data.get("domain"))
            subdomain_id = _resolve_organization_subdomain(db, domain_id, data.get("subdomain")) if domain_id else None
            db.execute(
                # street/city/state/postal_code (the "Main Address" fields —
                # see schema.sql's comment above the organizations table)
                # come straight from the file's own split columns when it
                # has them; full_address is the separate combined-text
                # column, independently parsed into the detailed
                # organization_addresses record just below.
                """INSERT INTO organizations
                   (tenant_id, organization_name, full_address, street, city, state, postal_code,
                    phone, email, website, organization_type_id, organization_domain_id,
                    organization_subdomain_id, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    g.tenant_id, name,
                    (data.get("address") or "").strip() or None,
                    (data.get("street") or "").strip() or None,
                    (data.get("city") or "").strip() or None,
                    (data.get("state") or "").strip() or None,
                    (data.get("postal_code") or "").strip() or None,
                    (data.get("phone") or "").strip() or None,
                    (data.get("email") or "").strip() or None,
                    (data.get("website") or "").strip() or None,
                    type_id, domain_id, subdomain_id,
                    (data.get("notes") or "").strip() or None,
                ),
            )
            org_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]

            addr = data.get("address_parsed") or {}
            if addr.get("street") or addr.get("country_id") or addr.get("country_text") \
                    or addr.get("state_id") or addr.get("state_text") or addr.get("city_id") or addr.get("city_text"):
                db.execute(
                    """INSERT INTO organization_addresses
                       (tenant_id, organization_id, address_type_id, street, region_id, country_id,
                        state_id, state_province_text, city_id, city_text, postal_code, is_primary)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (
                        g.tenant_id, org_id, mailing_address_type_id, addr.get("street") or None,
                        addr.get("region_id"), addr.get("country_id"),
                        addr.get("state_id"), (None if addr.get("state_id") else (addr.get("state_text") or None)),
                        addr.get("city_id"), (None if addr.get("city_id") else (addr.get("city_text") or None)),
                        addr.get("postal_code") or None,
                    ),
                )

            email = (data.get("email") or "").strip()
            if email:
                for addr_value in [e.strip() for e in email.split(";") if e.strip()]:
                    db.execute(
                        "INSERT INTO organization_emails (tenant_id, organization_id, email_address, is_primary) VALUES (?, ?, ?, 1)",
                        (g.tenant_id, org_id, addr_value),
                    )

            phone = (data.get("phone") or "").strip()
            if phone:
                for num in [p.strip() for p in phone.split(";") if p.strip()]:
                    db.execute(
                        "INSERT INTO organization_phones (tenant_id, organization_id, phone_type_id, number, is_primary) VALUES (?, ?, ?, ?, 1)",
                        (g.tenant_id, org_id, office_phone_type_id, num),
                    )

        db.execute(
            "UPDATE import_staging_rows SET committed_entity_id = ? WHERE staging_id = ? AND tenant_id = ?",
            (org_id, r["staging_id"], g.tenant_id),
        )
        committed += 1
    return committed


def _commit_ads_rows(db, rows):
    """Commit staged ad/flyer rows from Import Ads/Flyers
    (import_ads_flyers_extract above). Unlike the Organizations/Contacts
    CSV importers, EACH row may need its own new Organization — an ad's
    advertiser very often isn't in the system yet — and, if the ad names a
    specific person, a new Contact too. The Ad Listing itself is created
    with organizations.py's own unchanged helpers (_ad_dict_from_extracted/
    _find_ad_listing_by_headline/_create_ad_listing/_update_ad_listing_partial/
    _add_ad_note/_attach_ad_photo_file) — same dedup-by-headline and
    price-history behavior as every other way of importing an ad.

    Two rows sharing the same not-yet-existing advertiser name correctly
    resolve to the SAME new Organization: _apply_organization_from_card
    looks the name up fresh for every row, and an earlier row's INSERT in
    this same loop is already visible to that lookup on this connection.

    Photos: one photographed image can hold more than one distinct ad (see
    ad_import.extract_ads_for_import), so several rows can share one
    _photo_token — each token is promoted from pending to permanent
    storage at most once, and every row sharing it reuses that filename.

    committed_entity_id is set to the Organization, not the Ad Listing —
    "View organization" is the most useful link back from the review page,
    since that's exactly where the new ad now shows up (the existing Ads
    card on the Organization page, unchanged)."""
    committed = 0
    promoted_photos = {}  # photo_token -> permanent filename, or None
    for r in rows:
        data = json.loads(r["raw_data"])

        existing_org = None
        existing_org_id = data.get("_existing_org_id")
        if existing_org_id:
            existing_org = db.execute(
                "SELECT * FROM organizations WHERE organization_id = ? AND tenant_id = ?", (existing_org_id, g.tenant_id)
            ).fetchone()
        if not existing_org:
            existing_org = _find_organization_by_name(db, data.get("organization_name"))
        organization_id, _org_created = _apply_organization_from_card(db, data, existing_org)
        if not organization_id:
            continue  # no name and no match — extract-time validation should already have caught this

        _apply_contact_from_ad_data(db, data, organization_id)

        ad_data = _ad_dict_from_extracted(data)
        existing_ad = _find_ad_listing_by_headline(db, organization_id, ad_data["headline"])
        source = data.get("_source_filename") or "Ads/Flyers import"
        if existing_ad:
            _update_ad_listing_partial(db, existing_ad, ad_data)
            ad_id = existing_ad["ad_listing_id"]
        else:
            ad_id = _create_ad_listing(db, organization_id, ad_data, source=source)

        note_bits = []
        if data.get("source_notes"):
            note_bits.append(data["source_notes"])
        if data.get("uncertain_fields"):
            note_bits.append("Uncertain: " + ", ".join(data["uncertain_fields"]))
        if note_bits:
            _add_ad_note(db, ad_id, " ".join(note_bits), source=source)

        token = data.get("_photo_token")
        if token:
            if token not in promoted_photos:
                mime_type = data.get("_photo_mime") or "image/jpeg"
                pending_path = _pending_ad_path(token, mime_type)
                promoted_photos[token] = (
                    _promote_pending_ad_image(pending_path) if pending_path and os.path.exists(pending_path) else None
                )
            photo_filename = promoted_photos[token]
            if photo_filename:
                _attach_ad_photo_file(db, ad_id, photo_filename, data.get("_photo_mime") or "image/jpeg", source, source)

        db.execute(
            "UPDATE import_staging_rows SET committed_entity_id = ? WHERE staging_id = ? AND tenant_id = ?",
            (organization_id, r["staging_id"], g.tenant_id),
        )
        committed += 1
    return committed


COMMIT_HANDLERS = {
    "contacts": (_commit_contacts_rows, "contact(s)"),
    "organizations": (_commit_organizations_rows, "organization(s)"),
    "ads": (_commit_ads_rows, "ad(s)"),
}


@data_exchange_bp.route("/import/batches/<int:batch_id>/commit", methods=["POST"])
@login_required
def commit_batch(batch_id):
    db = get_db()
    batch = db.execute(
        "SELECT * FROM import_batches WHERE batch_id = ? AND tenant_id = ?", (batch_id, g.tenant_id)
    ).fetchone()
    if batch is None:
        abort(404)
    if batch["status"] == "Committed":
        flash("This batch was already committed.", "error")
        return redirect(url_for("data_exchange.review_batch", batch_id=batch_id))

    handler, noun = COMMIT_HANDLERS.get(batch["target_module"], (None, None))
    if handler is None:
        abort(400)

    rows = db.execute(
        "SELECT * FROM import_staging_rows WHERE batch_id = ? AND validation_status = 'Valid' AND committed_entity_id IS NULL",
        (batch_id,),
    ).fetchall()

    committed = handler(db, rows)

    db.execute(
        "UPDATE import_batches SET status = 'Committed' WHERE batch_id = ? AND tenant_id = ?", (batch_id, g.tenant_id)
    )
    db.commit()
    log_action("Import", "import_batch", batch_id, f"Committed {committed} rows into {batch['target_module']}")
    flash(f"Committed {committed} {noun}.", "success")
    return redirect(url_for("data_exchange.review_batch", batch_id=batch_id))


@data_exchange_bp.route("/import/batches/<int:batch_id>/reject", methods=["POST"])
@login_required
def reject_batch(batch_id):
    db = get_db()
    db.execute(
        "UPDATE import_batches SET status = 'Rejected' WHERE batch_id = ? AND tenant_id = ?", (batch_id, g.tenant_id)
    )
    db.commit()
    log_action("Import", "import_batch", batch_id, "Batch rejected")
    flash("Batch rejected — nothing was imported.", "success")
    return redirect(url_for("data_exchange.index"))
