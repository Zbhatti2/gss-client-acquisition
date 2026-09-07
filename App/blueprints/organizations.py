"""
Module — Organizations. A standalone management screen for the shared
`organizations` table — GSS names Organizations as a first-class module in
its own right (prospects/clients being pursued for acquisition), not just
an attribute of Contacts. Given its richer field set (address, phone,
email, type) compared to a plain code/label lookup, it gets its own
list/view/edit/delete pages here rather than living inside Table
Maintenance's simple lookup-table screen.

There's no organizations_archive table (unlike contacts_archive) — an
organization is closer to shared reference data than an owned record with
its own history, so deletion here follows the same pattern used for Table
Maintenance's lookup tables: blocked outright while anything still
references it (the database enforces this via PRAGMA foreign_keys = ON
regardless of what this code does), with a reassign/merge flow to
consolidate duplicates (e.g. "Acme Inc." vs "ACME, Inc." picked up from an
Outlook import) instead of a raw constraint error.
"""
import os
import re
import time
import uuid
import zipfile

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, send_from_directory, url_for

from ad_import import AD_TYPES, ExtractionError, extract_ads_from_image, iter_images_from_zip
from auth.decorators import login_required
from config import Config
from db import get_db, log_action
from utils import open_local_path

organizations_bp = Blueprint("organizations", __name__)

# Every master table that stores a foreign key to organizations.organization_id.
# GSS's clone of PIMS/TMS's data model excludes Points of Interest, Suppliers,
# and every other tourism-only module, so Contacts is the only referencing
# table here (see GSS_schema_v1.sql).
REFERENCES = [
    {"table": "contacts", "fk": "current_organization_id", "label": "contact(s)"},
]


def _usage_count(db, org_id):
    total = 0
    breakdown = []
    for ref in REFERENCES:
        count = db.execute(
            f"SELECT COUNT(*) c FROM {ref['table']} WHERE {ref['fk']} = ?", (org_id,)
        ).fetchone()["c"]
        if count:
            breakdown.append({"label": ref["label"], "count": count})
        total += count
    return total, breakdown


def _org_types(db):
    return db.execute(
        "SELECT * FROM organization_types WHERE is_active = 1 AND tenant_id = ? ORDER BY label COLLATE NOCASE", (g.tenant_id,)
    ).fetchall()


def _org_address_types(db):
    return db.execute(
        "SELECT * FROM organization_address_types WHERE is_active = 1 AND tenant_id = ? ORDER BY label COLLATE NOCASE",
        (g.tenant_id,),
    ).fetchall()


def _org_phone_types(db):
    return db.execute(
        "SELECT * FROM organization_phone_types WHERE is_active = 1 AND tenant_id = ? ORDER BY label COLLATE NOCASE",
        (g.tenant_id,),
    ).fetchall()


def _delete_org_ad_listings(db, org_id):
    """Removes every Ad Listing (and its price history/notes/photos, plus
    the underlying photo files on disk) belonging to org_id. Used when the
    organization itself is deleted or merged away — an Ad Listing is an
    owned record like an address or reference link (see this module's
    docstring), not something that blocks the delete."""
    ad_ids = [r["ad_listing_id"] for r in db.execute(
        "SELECT ad_listing_id FROM organization_ad_listings WHERE organization_id = ? AND tenant_id = ?",
        (org_id, g.tenant_id),
    ).fetchall()]
    for ad_id in ad_ids:
        for row in db.execute(
            "SELECT image_path FROM organization_ad_photos WHERE ad_listing_id = ? AND tenant_id = ?",
            (ad_id, g.tenant_id),
        ).fetchall():
            try:
                os.remove(os.path.join(Config.AD_PHOTOS_DIR, row["image_path"]))
            except OSError:
                pass
        db.execute("DELETE FROM organization_ad_photos WHERE ad_listing_id = ? AND tenant_id = ?", (ad_id, g.tenant_id))
        db.execute("DELETE FROM organization_ad_notes WHERE ad_listing_id = ? AND tenant_id = ?", (ad_id, g.tenant_id))
        db.execute("DELETE FROM organization_ad_price_history WHERE ad_listing_id = ? AND tenant_id = ?", (ad_id, g.tenant_id))
    db.execute("DELETE FROM organization_ad_listings WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))


def _int_or_none(value):
    """Parses a form field as an int, or None if blank/invalid — used for
    Number of Employees and the three classification foreign keys, all of
    which are optional (an organization can be left unclassified)."""
    value = (value or "").strip()
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _get_organization(db, org_id):
    org = db.execute(
        """SELECT o.*, ot.label AS type_label,
                  sc.label AS size_category_label,
                  od.label AS domain_label,
                  osd.label AS subdomain_label
           FROM organizations o
           LEFT JOIN organization_types ot ON ot.organization_type_id = o.organization_type_id
           LEFT JOIN organization_size_categories sc ON sc.size_category_id = o.size_category_id
           LEFT JOIN organization_domains od ON od.organization_domain_id = o.organization_domain_id
           LEFT JOIN organization_subdomains osd ON osd.organization_subdomain_id = o.organization_subdomain_id
           WHERE o.organization_id = ? AND o.tenant_id = ?""",
        (org_id, g.tenant_id),
    ).fetchone()
    if org is None:
        abort(404)
    return org


@organizations_bp.route("/")
@login_required
def list_organizations():
    db = get_db()
    q = request.args.get("q", "").strip()
    type_id = request.args.get("type_id", "").strip()
    city = request.args.get("city", "").strip()
    country_id = request.args.get("country_id", "").strip()
    sql = """
        SELECT o.*, ot.label AS type_label,
               COALESCE(pc.label, pa.city_text) AS city_label,
               COALESCE(ps.label, pa.state_province_text) AS state_label,
               pco.label AS country_label,
               pe.email_address AS primary_email,
               pp.country_code AS primary_phone_country_code,
               pp.area_code AS primary_phone_area_code,
               pp.number AS primary_phone_number,
               pp.extension AS primary_phone_extension
        FROM organizations o
        LEFT JOIN organization_types ot ON ot.organization_type_id = o.organization_type_id
        LEFT JOIN organization_addresses pa ON pa.organization_address_id = (
            SELECT a.organization_address_id FROM organization_addresses a
            WHERE a.organization_id = o.organization_id AND a.tenant_id = o.tenant_id
            ORDER BY a.is_primary DESC, a.organization_address_id ASC
            LIMIT 1
        )
        LEFT JOIN cities pc ON pc.city_id = pa.city_id
        LEFT JOIN states ps ON ps.state_id = pa.state_id
        LEFT JOIN countries pco ON pco.country_id = pa.country_id
        LEFT JOIN organization_emails pe ON pe.organization_email_id = (
            SELECT e.organization_email_id FROM organization_emails e
            WHERE e.organization_id = o.organization_id AND e.tenant_id = o.tenant_id
            ORDER BY e.is_primary DESC, e.organization_email_id ASC
            LIMIT 1
        )
        LEFT JOIN organization_phones pp ON pp.organization_phone_id = (
            SELECT ph.organization_phone_id FROM organization_phones ph
            WHERE ph.organization_id = o.organization_id AND ph.tenant_id = o.tenant_id
            ORDER BY ph.is_primary DESC, ph.organization_phone_id ASC
            LIMIT 1
        )
        WHERE o.tenant_id = ?
    """
    params = [g.tenant_id]
    if q:
        sql += " AND o.organization_name LIKE ?"
        params.append(f"%{q}%")
    if type_id:
        sql += " AND o.organization_type_id = ?"
        params.append(type_id)
    if city:
        # Matches the organization's primary address (same row the City
        # column on this list is built from) — a linked city_id (pc.label)
        # or, when the province/city isn't seeded in the geography lookups,
        # the free-text fallback (pa.city_text).
        sql += " AND (pc.label LIKE ? OR pa.city_text LIKE ?)"
        like = f"%{city}%"
        params += [like, like]
    if country_id:
        sql += " AND pa.country_id = ?"
        params.append(country_id)
    sql += " ORDER BY o.organization_name"
    rows = db.execute(sql, params).fetchall()

    orgs = []
    for r in rows:
        count, _ = _usage_count(db, r["organization_id"])
        orgs.append({"row": r, "usage_count": count})

    # Countries offered in the Country filter are limited to ones actually
    # in use on an organization's primary address, so the dropdown stays
    # short and every option is guaranteed to return results.
    country_options = db.execute(
        """SELECT DISTINCT co.country_id, co.label
           FROM organization_addresses oa
           JOIN countries co ON co.country_id = oa.country_id
           WHERE oa.tenant_id = ?
           ORDER BY co.label""",
        (g.tenant_id,),
    ).fetchall()

    return render_template(
        "organizations/list.html", orgs=orgs, q=q, org_types=_org_types(db),
        type_id=type_id, city=city, country_id=country_id, country_options=country_options,
    )


@organizations_bp.route("/classification-tree")
@login_required
def classification_tree():
    """Serves organization_size_categories/organization_domains/
    organization_subdomains — tenant-scoped, unlike geography's global
    tree (see blueprints/geography.py) — as one JSON payload, fetched once
    by the New/Edit Organization form's Domain -> SubDomain cascade and
    Number-of-Employees -> Size Category auto-suggest (see static/js/
    organization_classification.js). Same "fetch once, filter client-side"
    shape as /geography/tree."""
    db = get_db()
    size_categories = [dict(r) for r in db.execute(
        "SELECT size_category_id, label, min_employees, max_employees FROM organization_size_categories "
        "WHERE is_active = 1 AND tenant_id = ? ORDER BY sort_order, label COLLATE NOCASE",
        (g.tenant_id,),
    ).fetchall()]
    domains = [dict(r) for r in db.execute(
        "SELECT organization_domain_id, label FROM organization_domains "
        "WHERE is_active = 1 AND tenant_id = ? ORDER BY label COLLATE NOCASE",
        (g.tenant_id,),
    ).fetchall()]
    subdomains = [dict(r) for r in db.execute(
        "SELECT organization_subdomain_id, organization_domain_id, label FROM organization_subdomains "
        "WHERE is_active = 1 AND tenant_id = ? ORDER BY label COLLATE NOCASE",
        (g.tenant_id,),
    ).fetchall()]
    return jsonify({"size_categories": size_categories, "domains": domains, "subdomains": subdomains})


@organizations_bp.route("/<int:org_id>")
@login_required
def view_organization(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    contacts = db.execute(
        "SELECT contact_id, full_name, file_as FROM contacts "
        "WHERE current_organization_id = ? AND is_deleted = 0 ORDER BY file_as, full_name",
        (org_id,),
    ).fetchall()
    addresses = db.execute(
        """SELECT a.*, at.label AS address_type_label,
                  COALESCE(c.label, a.city_text) AS city_label,
                  COALESCE(st.label, a.state_province_text) AS state_label,
                  co.label AS country_label
           FROM organization_addresses a
           LEFT JOIN organization_address_types at ON at.address_type_id = a.address_type_id
           LEFT JOIN cities c ON c.city_id = a.city_id
           LEFT JOIN states st ON st.state_id = a.state_id
           LEFT JOIN countries co ON co.country_id = a.country_id
           WHERE a.organization_id = ? AND a.tenant_id = ?
           ORDER BY a.is_primary DESC, at.sort_order""",
        (org_id, g.tenant_id),
    ).fetchall()
    emails = db.execute(
        "SELECT * FROM organization_emails WHERE organization_id = ? AND tenant_id = ? ORDER BY is_primary DESC, email_address",
        (org_id, g.tenant_id),
    ).fetchall()
    phones = db.execute(
        """SELECT p.*, pt.label AS phone_type_label
           FROM organization_phones p
           LEFT JOIN organization_phone_types pt ON pt.phone_type_id = p.phone_type_id
           WHERE p.organization_id = ? AND p.tenant_id = ?
           ORDER BY p.is_primary DESC, pt.sort_order""",
        (org_id, g.tenant_id),
    ).fetchall()
    links = db.execute(
        "SELECT * FROM organization_reference_links WHERE organization_id = ? AND tenant_id = ? ORDER BY link_id",
        (org_id, g.tenant_id),
    ).fetchall()
    ad_count = db.execute(
        "SELECT COUNT(*) c FROM organization_ad_listings WHERE organization_id = ? AND tenant_id = ?",
        (org_id, g.tenant_id),
    ).fetchone()["c"]
    return render_template(
        "organizations/view.html", org=org, contacts=contacts, addresses=addresses,
        emails=emails, phones=phones, links=links, ad_count=ad_count,
    )


@organizations_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_organization():
    db = get_db()
    if request.method == "POST":
        form = request.form
        name = form.get("organization_name", "").strip()
        if not name:
            flash("Organization name is required.", "error")
            return render_template("organizations/form.html", org=None, org_types=_org_types(db))
        db.execute(
            # Main Address (as separate Street/City/State/Zip fields) plus
            # Main Phone/Fax/Email are plain quick-contact fields stored
            # directly on organizations (street/city/state/postal_code/
            # phone/fax/email — see schema.sql's comment above the table) —
            # separate from the detailed, multi-valued organization_addresses/
            # organization_emails/organization_phones child tables (their own
            # cards on the view page), and never required: most Organizations
            # here are prospects/leads and plenty never get a full address.
            # full_address (the older single-blob version of this) is
            # deliberately left out of this INSERT — this form doesn't read
            # or write it; see the module note in schema.sql.
            "INSERT INTO organizations (tenant_id, organization_name, street, city, state, postal_code, "
            "phone, fax, email, website, organization_type_id, notes, number_of_employees, size_category_id, "
            "organization_domain_id, organization_subdomain_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                g.tenant_id,
                name,
                form.get("main_street", "").strip() or None,
                form.get("main_city", "").strip() or None,
                form.get("main_state", "").strip() or None,
                form.get("main_postal_code", "").strip() or None,
                form.get("main_phone", "").strip() or None,
                form.get("main_fax", "").strip() or None,
                form.get("main_email", "").strip() or None,
                form.get("website", "").strip() or None,
                form.get("organization_type_id") or None,
                form.get("notes", "").strip() or None,
                _int_or_none(form.get("number_of_employees")),
                _int_or_none(form.get("size_category_id")),
                _int_or_none(form.get("organization_domain_id")),
                _int_or_none(form.get("organization_subdomain_id")),
            ),
        )
        db.commit()
        org_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        log_action("Create", "organization", org_id, f"Created organization {name}")
        flash("Organization created.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template("organizations/form.html", org=None, org_types=_org_types(db))


@organizations_bp.route("/<int:org_id>/edit", methods=["GET", "POST"])
@login_required
def edit_organization(org_id):
    db = get_db()
    org = db.execute(
        "SELECT * FROM organizations WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id)
    ).fetchone()
    if org is None:
        abort(404)
    if request.method == "POST":
        form = request.form
        name = form.get("organization_name", "").strip()
        if not name:
            flash("Organization name is required.", "error")
            return render_template("organizations/form.html", org=org, org_types=_org_types(db))
        db.execute(
            # See the matching note in new_organization above — Main Address
            # (street/city/state/postal_code)/Phone/Fax/Email are the plain
            # quick-contact fields, distinct from the organization_addresses/
            # emails/phones cards. full_address is deliberately not in this
            # SET list — this form never touches it, so whatever Contacts'
            # quick-add or the CSV importer put there (if anything) survives
            # untouched across edits made here.
            "UPDATE organizations SET organization_name=?, street=?, city=?, state=?, postal_code=?, "
            "phone=?, fax=?, email=?, website=?, "
            "organization_type_id=?, notes=?, number_of_employees=?, size_category_id=?, "
            "organization_domain_id=?, organization_subdomain_id=?, updated_at=datetime('now') "
            "WHERE organization_id=? AND tenant_id=?",
            (
                name,
                form.get("main_street", "").strip() or None,
                form.get("main_city", "").strip() or None,
                form.get("main_state", "").strip() or None,
                form.get("main_postal_code", "").strip() or None,
                form.get("main_phone", "").strip() or None,
                form.get("main_fax", "").strip() or None,
                form.get("main_email", "").strip() or None,
                form.get("website", "").strip() or None,
                form.get("organization_type_id") or None,
                form.get("notes", "").strip() or None,
                _int_or_none(form.get("number_of_employees")),
                _int_or_none(form.get("size_category_id")),
                _int_or_none(form.get("organization_domain_id")),
                _int_or_none(form.get("organization_subdomain_id")),
                org_id,
                g.tenant_id,
            ),
        )
        db.commit()
        log_action("Update", "organization", org_id, f"Updated organization {name}")
        flash("Organization updated — anywhere it's referenced will show the new details immediately.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template("organizations/form.html", org=org, org_types=_org_types(db))


@organizations_bp.route("/<int:org_id>/delete", methods=["POST"])
@login_required
def delete_organization(org_id):
    db = get_db()
    org = db.execute(
        "SELECT * FROM organizations WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id)
    ).fetchone()
    if org is None:
        abort(404)
    count, _ = _usage_count(db, org_id)
    if count > 0:
        flash(
            f"'{org['organization_name']}' is still linked to {count} record(s), so it can't be deleted outright. "
            f"Reassign those records to a different organization first.",
            "error",
        )
        return redirect(url_for("organizations.reassign_organization", org_id=org_id))
    # An organization's addresses/emails/phones/reference links/ad listings
    # belong to it (like its notes), not other records referencing it, so
    # they're removed along with it rather than counted in
    # _usage_count/blocking the delete.
    db.execute("DELETE FROM organization_addresses WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
    db.execute("DELETE FROM organization_emails WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
    db.execute("DELETE FROM organization_phones WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
    db.execute("DELETE FROM organization_reference_links WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
    _delete_org_ad_listings(db, org_id)
    db.execute("DELETE FROM organizations WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
    db.commit()
    log_action("Delete", "organization", org_id, f"Deleted unused organization {org['organization_name']}")
    flash(f"'{org['organization_name']}' deleted.", "success")
    return redirect(url_for("organizations.list_organizations"))


@organizations_bp.route("/<int:org_id>/reassign", methods=["GET", "POST"])
@login_required
def reassign_organization(org_id):
    """Bulk-move every contact/personal account/software license that
    points at `org_id` over to a different organization, then optionally
    delete the old one. This is also the tool for merging duplicate
    organizations (e.g. "Acme Inc." vs "ACME, Inc." picked up from an
    import), independent of any delete attempt — reachable directly from
    the list as "Merge into..."."""
    db = get_db()
    org = db.execute(
        "SELECT * FROM organizations WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id)
    ).fetchone()
    if org is None:
        abort(404)
    count, breakdown = _usage_count(db, org_id)
    others = db.execute(
        "SELECT * FROM organizations WHERE organization_id != ? AND tenant_id = ? ORDER BY organization_name",
        (org_id, g.tenant_id),
    ).fetchall()

    if request.method == "POST":
        target_id = request.form.get("target_id")
        also_delete = bool(request.form.get("also_delete"))
        if not target_id:
            flash("Choose an organization to reassign these records to.", "error")
            return redirect(url_for("organizations.reassign_organization", org_id=org_id))
        target_id = int(target_id)
        target = db.execute(
            "SELECT * FROM organizations WHERE organization_id = ? AND tenant_id = ?", (target_id, g.tenant_id)
        ).fetchone()
        if target is None:
            abort(404)

        moved = 0
        for ref in REFERENCES:
            cur = db.execute(
                f"UPDATE {ref['table']} SET {ref['fk']} = ? WHERE {ref['fk']} = ? AND tenant_id = ?",
                (target_id, org_id, g.tenant_id),
            )
            moved += cur.rowcount

        if also_delete:
            # Same reasoning as delete_organization above — the merged-away
            # organization's own addresses/emails/phones/reference
            # links/ad listings aren't moved to the survivor (nothing else
            # about it is, either — notes are discarded the same way), just
            # cleared so the delete succeeds.
            db.execute("DELETE FROM organization_addresses WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
            db.execute("DELETE FROM organization_emails WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
            db.execute("DELETE FROM organization_phones WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
            db.execute("DELETE FROM organization_reference_links WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
            _delete_org_ad_listings(db, org_id)
            db.execute("DELETE FROM organizations WHERE organization_id = ? AND tenant_id = ?", (org_id, g.tenant_id))
        db.commit()

        log_action(
            "Update", "organization", org_id,
            f"Reassigned {moved} record(s) from '{org['organization_name']}' to '{target['organization_name']}'"
            + (" and deleted the old organization" if also_delete else ""),
        )
        flash(
            f"Moved {moved} record(s) from '{org['organization_name']}' to '{target['organization_name']}'."
            + (
                f" '{org['organization_name']}' was then deleted."
                if also_delete
                else f" '{org['organization_name']}' is still in the list with nothing pointing at it "
                     f"— delete it separately whenever you like."
            ),
            "success",
        )
        return redirect(url_for("organizations.list_organizations"))

    return render_template(
        "organizations/reassign.html",
        org=org, others=others, usage_count=count, usage_breakdown=breakdown,
    )


# --------------------------------------------------------------- addresses
#
# An organization can have more than one address (e.g. Mailing Address,
# Physical Address — see organization_address_types). Mirrors Suppliers'
# supplier_addresses CRUD (blueprints/suppliers.py) exactly, but against its
# own, separate organization_addresses table and organization_address_types
# lookup, per the standing Organizations/Suppliers separation rule.

@organizations_bp.route("/<int:org_id>/addresses/new", methods=["GET", "POST"])
@login_required
def new_organization_address(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    if request.method == "POST":
        form = request.form
        if form.get("is_primary"):
            db.execute(
                "UPDATE organization_addresses SET is_primary = 0 WHERE organization_id = ? AND tenant_id = ?",
                (org_id, g.tenant_id),
            )
        db.execute(
            """INSERT INTO organization_addresses
               (tenant_id, organization_id, address_type_id, street, unit, region_id, country_id,
                state_id, state_province_text, city_id, city_text, postal_code, is_primary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                g.tenant_id, org_id, form.get("address_type_id") or None,
                form.get("street", "").strip() or None, form.get("unit", "").strip() or None,
                form.get("region_id") or None, form.get("country_id") or None,
                form.get("state_id") or None, form.get("state_province_text", "").strip() or None,
                form.get("city_id") or None, form.get("city_text", "").strip() or None,
                form.get("postal_code", "").strip() or None, 1 if form.get("is_primary") else 0,
            ),
        )
        db.commit()
        log_action("Create", "organization_address", org_id, "Added organization address")
        flash("Address added.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template(
        "organizations/address_form.html", org=org, address=None, address_types=_org_address_types(db)
    )


@organizations_bp.route("/<int:org_id>/addresses/<int:address_id>/edit", methods=["GET", "POST"])
@login_required
def edit_organization_address(org_id, address_id):
    db = get_db()
    org = _get_organization(db, org_id)
    address = db.execute(
        "SELECT * FROM organization_addresses WHERE organization_address_id = ? AND organization_id = ? AND tenant_id = ?",
        (address_id, org_id, g.tenant_id),
    ).fetchone()
    if address is None:
        abort(404)
    if request.method == "POST":
        form = request.form
        if form.get("is_primary"):
            db.execute(
                "UPDATE organization_addresses SET is_primary = 0 WHERE organization_id = ? AND tenant_id = ?",
                (org_id, g.tenant_id),
            )
        db.execute(
            """UPDATE organization_addresses SET address_type_id=?, street=?, unit=?, region_id=?, country_id=?,
               state_id=?, state_province_text=?, city_id=?, city_text=?, postal_code=?, is_primary=?,
               updated_at=datetime('now') WHERE organization_address_id=? AND tenant_id=?""",
            (
                form.get("address_type_id") or None, form.get("street", "").strip() or None,
                form.get("unit", "").strip() or None,
                form.get("region_id") or None, form.get("country_id") or None,
                form.get("state_id") or None, form.get("state_province_text", "").strip() or None,
                form.get("city_id") or None, form.get("city_text", "").strip() or None,
                form.get("postal_code", "").strip() or None, 1 if form.get("is_primary") else 0,
                address_id, g.tenant_id,
            ),
        )
        db.commit()
        log_action("Update", "organization_address", org_id, f"Updated organization address #{address_id}")
        flash("Address updated.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template(
        "organizations/address_form.html", org=org, address=address, address_types=_org_address_types(db)
    )


@organizations_bp.route("/<int:org_id>/addresses/<int:address_id>/delete", methods=["POST"])
@login_required
def delete_organization_address(org_id, address_id):
    db = get_db()
    _get_organization(db, org_id)
    address = db.execute(
        "SELECT * FROM organization_addresses WHERE organization_address_id = ? AND organization_id = ? AND tenant_id = ?",
        (address_id, org_id, g.tenant_id),
    ).fetchone()
    if address is None:
        abort(404)
    db.execute(
        "DELETE FROM organization_addresses WHERE organization_address_id = ? AND tenant_id = ?",
        (address_id, g.tenant_id),
    )
    db.commit()
    log_action("Delete", "organization_address", org_id, f"Deleted organization address #{address_id}")
    flash("Address deleted.", "success")
    return redirect(url_for("organizations.view_organization", org_id=org_id))


# ------------------------------------------------------------------ emails
#
# An organization can have more than one email address. Mirrors Contacts'
# contact_emails CRUD (blueprints/contacts.py) but against its own,
# separate organization_emails table, and without history tracking —
# Organizations is master/reference data here, not an owned record with
# its own audit trail (see this module's docstring).

@organizations_bp.route("/<int:org_id>/emails/new", methods=["GET", "POST"])
@login_required
def new_organization_email(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    if request.method == "POST":
        form = request.form
        if form.get("is_primary"):
            db.execute(
                "UPDATE organization_emails SET is_primary = 0 WHERE organization_id = ? AND tenant_id = ?",
                (org_id, g.tenant_id),
            )
        db.execute(
            "INSERT INTO organization_emails (tenant_id, organization_id, email_address, is_primary) VALUES (?, ?, ?, ?)",
            (g.tenant_id, org_id, form["email_address"].strip(), 1 if form.get("is_primary") else 0),
        )
        db.commit()
        log_action("Create", "organization_email", org_id, f"Added email {form['email_address']}")
        flash("Email added.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template("organizations/email_form.html", org=org, email=None)


@organizations_bp.route("/<int:org_id>/emails/<int:email_id>/edit", methods=["GET", "POST"])
@login_required
def edit_organization_email(org_id, email_id):
    db = get_db()
    org = _get_organization(db, org_id)
    email = db.execute(
        "SELECT * FROM organization_emails WHERE organization_email_id = ? AND organization_id = ? AND tenant_id = ?",
        (email_id, org_id, g.tenant_id),
    ).fetchone()
    if email is None:
        abort(404)
    if request.method == "POST":
        form = request.form
        if form.get("is_primary"):
            db.execute(
                "UPDATE organization_emails SET is_primary = 0 WHERE organization_id = ? AND tenant_id = ?",
                (org_id, g.tenant_id),
            )
        db.execute(
            "UPDATE organization_emails SET email_address = ?, is_primary = ?, updated_at = datetime('now') "
            "WHERE organization_email_id = ? AND tenant_id = ?",
            (form["email_address"].strip(), 1 if form.get("is_primary") else 0, email_id, g.tenant_id),
        )
        db.commit()
        log_action("Update", "organization_email", org_id, f"Updated email #{email_id}")
        flash("Email updated.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template("organizations/email_form.html", org=org, email=email)


@organizations_bp.route("/<int:org_id>/emails/<int:email_id>/delete", methods=["POST"])
@login_required
def delete_organization_email(org_id, email_id):
    db = get_db()
    _get_organization(db, org_id)
    email = db.execute(
        "SELECT * FROM organization_emails WHERE organization_email_id = ? AND organization_id = ? AND tenant_id = ?",
        (email_id, org_id, g.tenant_id),
    ).fetchone()
    if email is None:
        abort(404)
    db.execute(
        "DELETE FROM organization_emails WHERE organization_email_id = ? AND tenant_id = ?", (email_id, g.tenant_id)
    )
    db.commit()
    log_action("Delete", "organization_email", org_id, f"Deleted email #{email_id}")
    flash("Email deleted.", "success")
    return redirect(url_for("organizations.view_organization", org_id=org_id))


# ------------------------------------------------------------------ phones
#
# An organization can have more than one phone number (Office, Mobile,
# Fax, ... — see organization_phone_types). Mirrors the addresses CRUD
# above in shape.

@organizations_bp.route("/<int:org_id>/phones/new", methods=["GET", "POST"])
@login_required
def new_organization_phone(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    if request.method == "POST":
        form = request.form
        if form.get("is_primary"):
            db.execute(
                "UPDATE organization_phones SET is_primary = 0 WHERE organization_id = ? AND tenant_id = ?",
                (org_id, g.tenant_id),
            )
        db.execute(
            """INSERT INTO organization_phones
               (tenant_id, organization_id, phone_type_id, country_code, area_code, number, extension, is_primary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                g.tenant_id, org_id, form.get("phone_type_id") or None,
                form.get("country_code", "").strip() or None, form.get("area_code", "").strip() or None,
                form["number"].strip(), form.get("extension", "").strip() or None,
                1 if form.get("is_primary") else 0,
            ),
        )
        db.commit()
        log_action("Create", "organization_phone", org_id, "Added organization phone")
        flash("Phone added.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template("organizations/phone_form.html", org=org, phone=None, phone_types=_org_phone_types(db))


@organizations_bp.route("/<int:org_id>/phones/<int:phone_id>/edit", methods=["GET", "POST"])
@login_required
def edit_organization_phone(org_id, phone_id):
    db = get_db()
    org = _get_organization(db, org_id)
    phone = db.execute(
        "SELECT * FROM organization_phones WHERE organization_phone_id = ? AND organization_id = ? AND tenant_id = ?",
        (phone_id, org_id, g.tenant_id),
    ).fetchone()
    if phone is None:
        abort(404)
    if request.method == "POST":
        form = request.form
        if form.get("is_primary"):
            db.execute(
                "UPDATE organization_phones SET is_primary = 0 WHERE organization_id = ? AND tenant_id = ?",
                (org_id, g.tenant_id),
            )
        db.execute(
            """UPDATE organization_phones SET phone_type_id=?, country_code=?, area_code=?, number=?, extension=?,
               is_primary=?, updated_at=datetime('now') WHERE organization_phone_id=? AND tenant_id=?""",
            (
                form.get("phone_type_id") or None, form.get("country_code", "").strip() or None,
                form.get("area_code", "").strip() or None, form["number"].strip(),
                form.get("extension", "").strip() or None, 1 if form.get("is_primary") else 0,
                phone_id, g.tenant_id,
            ),
        )
        db.commit()
        log_action("Update", "organization_phone", org_id, f"Updated organization phone #{phone_id}")
        flash("Phone updated.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template("organizations/phone_form.html", org=org, phone=phone, phone_types=_org_phone_types(db))


@organizations_bp.route("/<int:org_id>/phones/<int:phone_id>/delete", methods=["POST"])
@login_required
def delete_organization_phone(org_id, phone_id):
    db = get_db()
    _get_organization(db, org_id)
    phone = db.execute(
        "SELECT * FROM organization_phones WHERE organization_phone_id = ? AND organization_id = ? AND tenant_id = ?",
        (phone_id, org_id, g.tenant_id),
    ).fetchone()
    if phone is None:
        abort(404)
    db.execute(
        "DELETE FROM organization_phones WHERE organization_phone_id = ? AND tenant_id = ?", (phone_id, g.tenant_id)
    )
    db.commit()
    log_action("Delete", "organization_phone", org_id, f"Deleted organization phone #{phone_id}")
    flash("Phone deleted.", "success")
    return redirect(url_for("organizations.view_organization", org_id=org_id))


# ------------------------------------------------------------- reference links
#
# "Documents Link" feature — an organization can have any number of
# reference links (a web URL and/or a local document path, each with a
# short description/notes). Mirrors Contacts' contact_reference_links CRUD
# (blueprints/contacts.py) against its own, separate
# organization_reference_links table.

@organizations_bp.route("/<int:org_id>/links/new", methods=["GET", "POST"])
@login_required
def new_organization_link(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    if request.method == "POST":
        form = request.form
        db.execute(
            "INSERT INTO organization_reference_links (tenant_id, organization_id, url, document_path, description, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                g.tenant_id, org_id, form.get("url", "").strip() or None, form.get("document_path", "").strip() or None,
                form.get("description", "").strip() or None, form.get("notes", "").strip() or None,
            ),
        )
        db.commit()
        log_action("Create", "organization_reference_link", org_id, "Added reference link")
        flash("Reference link added.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template("organizations/link_form.html", org=org, link=None)


@organizations_bp.route("/<int:org_id>/links/<int:link_id>/edit", methods=["GET", "POST"])
@login_required
def edit_organization_link(org_id, link_id):
    db = get_db()
    org = _get_organization(db, org_id)
    link = db.execute(
        "SELECT * FROM organization_reference_links WHERE link_id = ? AND organization_id = ? AND tenant_id = ?",
        (link_id, org_id, g.tenant_id),
    ).fetchone()
    if link is None:
        abort(404)
    if request.method == "POST":
        form = request.form
        db.execute(
            "UPDATE organization_reference_links SET url = ?, document_path = ?, description = ?, notes = ? "
            "WHERE link_id = ? AND organization_id = ? AND tenant_id = ?",
            (
                form.get("url", "").strip() or None, form.get("document_path", "").strip() or None,
                form.get("description", "").strip() or None, form.get("notes", "").strip() or None,
                link_id, org_id, g.tenant_id,
            ),
        )
        db.commit()
        log_action("Update", "organization_reference_link", org_id, f"Updated reference link #{link_id}")
        flash("Reference link updated.", "success")
        return redirect(url_for("organizations.view_organization", org_id=org_id))
    return render_template("organizations/link_form.html", org=org, link=link)


@organizations_bp.route("/<int:org_id>/links/<int:link_id>/delete", methods=["POST"])
@login_required
def delete_organization_link(org_id, link_id):
    db = get_db()
    _get_organization(db, org_id)
    db.execute(
        "DELETE FROM organization_reference_links WHERE link_id = ? AND organization_id = ? AND tenant_id = ?",
        (link_id, org_id, g.tenant_id),
    )
    db.commit()
    log_action("Delete", "organization_reference_link", org_id, f"Deleted reference link #{link_id}")
    flash("Reference link deleted.", "success")
    return redirect(url_for("organizations.view_organization", org_id=org_id))


@organizations_bp.route("/<int:org_id>/links/<int:link_id>/open")
@login_required
def open_organization_link(org_id, link_id):
    db = get_db()
    link = db.execute(
        "SELECT * FROM organization_reference_links WHERE link_id = ? AND organization_id = ? AND tenant_id = ?",
        (link_id, org_id, g.tenant_id),
    ).fetchone()
    if link is None:
        return jsonify(ok=False, error="Reference link not found."), 404
    path = link["document_path"]
    if not path:
        return jsonify(ok=False, error="No document path on this reference link.")
    if not os.path.exists(path):
        return jsonify(ok=False, error=f"File not found on disk: {path}")
    try:
        open_local_path(path)
    except Exception as e:
        return jsonify(ok=False, error=f"Couldn't open the file: {e}")
    log_action("Open", "organization_reference_link", org_id, f"Opened {path}")
    return jsonify(ok=True)


# ------------------------------------------------------------- ad listings
#
# "Import Ad(s)" — an Organization's advertising/marketing material (a
# magazine ad, a classified, a social-media post screenshot, an online ad,
# a flyer...) captured as an Ad Listing, with the ORIGINAL ad photo(s)
# always kept attached (organization_ad_photos) — that's what "maintain the
# original ads in a listing" means below. This is a direct port of the Real
# Estate Agent reference app's admin.py photo-import feature:
#   - one image at a time -> AI extraction -> human review/edit -> Save
#     (find_listing_by_address there is find-by-headline here)
#   - a zip of many images -> AI extraction -> auto-save every ad found,
#     no review step, with a results report (created/updated/errored)
# A single photo can contain more than one distinct ad (e.g. a page of
# classifieds) — ad_import.py's extraction always returns a LIST of ads per
# image, so both flows below loop over that list.

AD_PHOTO_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp"}
PENDING_AD_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_BATCH_AD_IMAGES = 40  # same cap the reference app uses for its batch flyer import


def _get_ad_listing(db, org_id, ad_id):
    ad = db.execute(
        "SELECT * FROM organization_ad_listings WHERE ad_listing_id = ? AND organization_id = ? AND tenant_id = ?",
        (ad_id, org_id, g.tenant_id),
    ).fetchone()
    if ad is None:
        abort(404)
    return ad


def _find_ad_listing_by_headline(db, org_id, headline):
    """The dedup/match key for an Ad Listing, mirroring the reference app's
    find_listing_by_address — an ad's headline is the single most durable,
    human-recognizable identifier a re-imported photo of the *same* ad is
    expected to still carry."""
    headline = (headline or "").strip()
    if not headline:
        return None
    return db.execute(
        "SELECT * FROM organization_ad_listings WHERE organization_id = ? AND tenant_id = ? "
        "AND lower(trim(headline)) = lower(?)",
        (org_id, g.tenant_id, headline),
    ).fetchone()


def _ad_dict_from_extracted(item):
    """Normalizes one ad dict from ad_import.extract_ads_from_image (or a
    review-form submission shaped the same way) into clean column values."""
    ad_type = (item.get("ad_type") or "").strip()
    if ad_type not in AD_TYPES:
        ad_type = "Other"
    price = item.get("price")
    try:
        price = float(price) if price not in (None, "") else None
    except (TypeError, ValueError):
        price = None
    return {
        "headline": (item.get("headline") or "").strip() or "Untitled ad",
        "ad_type": ad_type,
        "publication": (item.get("publication") or "").strip() or None,
        "date_published": (item.get("date_published") or "").strip() or None,
        "description": (item.get("description") or "").strip() or None,
        "offer_details": (item.get("offer_details") or "").strip() or None,
        "price": price,
        "price_label": (item.get("price_label") or "").strip() or None,
        "contact_name": (item.get("contact_name") or "").strip() or None,
        "contact_phone": (item.get("contact_phone") or "").strip() or None,
        "contact_email": (item.get("contact_email") or "").strip() or None,
    }


def _create_ad_listing(db, org_id, data, source=None):
    db.execute(
        """INSERT INTO organization_ad_listings
           (tenant_id, organization_id, headline, ad_type, publication, date_published,
            description, offer_details, price, price_label, contact_name, contact_phone,
            contact_email, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            g.tenant_id, org_id, data["headline"], data["ad_type"], data["publication"],
            data["date_published"], data["description"], data["offer_details"], data["price"],
            data["price_label"], data["contact_name"], data["contact_phone"], data["contact_email"], source,
        ),
    )
    ad_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
    if data["price"] is not None:
        db.execute(
            "INSERT INTO organization_ad_price_history (tenant_id, ad_listing_id, price, price_label, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (g.tenant_id, ad_id, data["price"], data["price_label"], "Initial price at import"),
        )
    return ad_id


def _update_ad_listing_partial(db, existing, data):
    """Updates an existing Ad Listing with newly-extracted data. Unlike
    Business Card import's fill-blank-only semantics, a re-imported ad is
    treated as a refresh of the SAME listing (a follow-up photo of the same
    ad, or a later re-run) — any newly-extracted field that isn't blank
    overwrites what's on file; a field the new extraction didn't read is
    left untouched rather than blanked out. A changed price is never
    silently overwritten — the OLD price/label is preserved as a
    price_history row first, mirroring the reference app's listing
    price-change tracking (price_history.price is NOT NULL, so this only
    fires when there was an actual prior price to record)."""
    ad_id = existing["ad_listing_id"]
    new_price = data.get("price")
    if new_price is not None and existing["price"] is not None and new_price != existing["price"]:
        db.execute(
            "INSERT INTO organization_ad_price_history (tenant_id, ad_listing_id, price, price_label, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (g.tenant_id, ad_id, existing["price"], existing["price_label"], "Price before this update"),
        )

    updates, params = [], []
    for col in ("headline", "ad_type", "publication", "date_published", "description",
                "offer_details", "price_label", "contact_name", "contact_phone", "contact_email"):
        val = data.get(col)
        if val not in (None, ""):
            updates.append(f"{col} = ?")
            params.append(val)
    if new_price is not None:
        updates.append("price = ?")
        params.append(new_price)
    if not updates:
        return
    updates.append("updated_at = datetime('now')")
    params += [ad_id, g.tenant_id]
    db.execute(
        f"UPDATE organization_ad_listings SET {', '.join(updates)} WHERE ad_listing_id = ? AND tenant_id = ?", params
    )


def _add_ad_note(db, ad_id, note_text, source=None):
    note_text = (note_text or "").strip()
    if not note_text:
        return
    db.execute(
        "INSERT INTO organization_ad_notes (tenant_id, ad_listing_id, note_text, source) VALUES (?, ?, ?, ?)",
        (g.tenant_id, ad_id, note_text, source),
    )


def _pending_ad_path(token, mime_type):
    """Path for a not-yet-saved ad photo, identified by the random token
    minted at extract time — same token+temp-file architecture as Data
    Exchange's business-card import (see _pending_card_path there): the
    review form carries forward only this token, never the image bytes,
    since a full-size photo as base64 in a hidden field blows well past
    Werkzeug's 500KB max_form_memory_size for non-file fields. Token is
    validated against the exact shape uuid4().hex always produces before
    it's allowed anywhere near a filesystem path, since it also arrives on
    the pending_ad_image GET route as a plain URL segment."""
    if not PENDING_AD_TOKEN_RE.match(token or ""):
        return None
    ext = AD_PHOTO_EXT.get(mime_type, "jpg")
    return os.path.join(Config.PENDING_ADS_DIR, f"{token}.{ext}")


def _save_pending_ad_image(token, image_bytes, mime_type):
    with open(_pending_ad_path(token, mime_type), "wb") as f:
        f.write(image_bytes)


def _cleanup_stale_pending_ads(max_age_seconds=6 * 3600):
    """Best-effort sweep of abandoned pending-ad temp files — an extract
    that's never saved would otherwise leave its image file here forever.
    Runs opportunistically on each new extract, same as
    _cleanup_stale_pending_cards."""
    try:
        now = time.time()
        for name in os.listdir(Config.PENDING_ADS_DIR):
            path = os.path.join(Config.PENDING_ADS_DIR, name)
            try:
                if now - os.path.getmtime(path) > max_age_seconds:
                    os.remove(path)
            except OSError:
                pass
    except OSError:
        pass


def _promote_pending_ad_image(pending_path):
    """Moves a validated pending-ad temp file into the permanent
    organization-ads uploads directory under a fresh random filename, once
    a Save has actually happened. Returns the stored filename (not the full
    path)."""
    ext = pending_path.rsplit(".", 1)[-1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.replace(pending_path, os.path.join(Config.AD_PHOTOS_DIR, filename))
    return filename


def _save_ad_photo_bytes(image_bytes, mime_type):
    """Writes image bytes straight to the permanent ad-photos directory
    under a fresh random filename — used by the no-review batch/zip import,
    which has no pending/review step to promote from. Returns the stored
    filename."""
    ext = AD_PHOTO_EXT.get(mime_type, "jpg")
    filename = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(Config.AD_PHOTOS_DIR, filename), "wb") as f:
        f.write(image_bytes)
    return filename


def _attach_ad_photo_file(db, ad_id, filename, mime_type, original_filename, source):
    """Links an already-saved image file (see _save_ad_photo_bytes /
    _promote_pending_ad_image) to an Ad Listing as one of its original-ad
    photos — this is what "maintain the original ads in a listing" means.
    De-dupes by (ad_listing_id, source, byte size) so re-running the same
    import over the same photo doesn't pile up duplicate rows — same
    convention as the reference app's _attach_photo_bytes."""
    try:
        size = os.path.getsize(os.path.join(Config.AD_PHOTOS_DIR, filename))
    except OSError:
        size = None
    if source and size is not None:
        for row in db.execute(
            "SELECT image_path FROM organization_ad_photos WHERE ad_listing_id = ? AND tenant_id = ? AND source = ?",
            (ad_id, g.tenant_id, source),
        ).fetchall():
            try:
                if os.path.getsize(os.path.join(Config.AD_PHOTOS_DIR, row["image_path"])) == size:
                    return  # same photo already attached to this ad from this source — skip the duplicate
            except OSError:
                pass
    db.execute(
        "INSERT INTO organization_ad_photos (tenant_id, ad_listing_id, image_path, mime_type, original_filename, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (g.tenant_id, ad_id, filename, mime_type, original_filename, source),
    )


def _save_extracted_ad_item(db, org_id, item, photo_filename, mime_type, original_filename, source):
    """Auto-saves one extracted ad dict against org_id — matched by
    headline, update-in-place if found, else create — then links the given
    already-saved photo file to it and records a note tagging the source
    image plus anything Claude flagged as uncertain. Mirrors the reference
    app's _save_extracted_item. Returns (ad_id, was_update)."""
    data = _ad_dict_from_extracted(item)
    existing = _find_ad_listing_by_headline(db, org_id, data["headline"])
    if existing:
        _update_ad_listing_partial(db, existing, data)
        ad_id = existing["ad_listing_id"]
        was_update = True
    else:
        ad_id = _create_ad_listing(db, org_id, data, source=source)
        was_update = False

    note_bits = []
    if item.get("source_notes"):
        note_bits.append(item["source_notes"])
    if item.get("uncertain_fields"):
        note_bits.append("Uncertain: " + ", ".join(item["uncertain_fields"]))
    _add_ad_note(db, ad_id, " ".join(note_bits), source=source)

    _attach_ad_photo_file(db, ad_id, photo_filename, mime_type, original_filename, source)
    db.commit()
    return ad_id, was_update


# ---- manual CRUD: list / new / edit (+ price history/notes/photos) / delete

@organizations_bp.route("/<int:org_id>/ads")
@login_required
def list_ads(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    ads = db.execute(
        "SELECT * FROM organization_ad_listings WHERE organization_id = ? AND tenant_id = ? ORDER BY updated_at DESC",
        (org_id, g.tenant_id),
    ).fetchall()
    return render_template("organizations/ads_list.html", org=org, ads=ads)


@organizations_bp.route("/<int:org_id>/ads/new", methods=["GET", "POST"])
@login_required
def new_ad(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    if request.method == "POST":
        form = request.form
        headline = form.get("headline", "").strip()
        if not headline:
            flash("Headline is required.", "error")
            return render_template(
                "organizations/ad_form.html", org=org, ad=None, ad_types=AD_TYPES,
                price_history=[], notes=[], photos=[],
            )
        price = form.get("price", "").strip()
        try:
            price = float(price) if price else None
        except ValueError:
            price = None
        price_label = form.get("price_label", "").strip() or None
        db.execute(
            """INSERT INTO organization_ad_listings
               (tenant_id, organization_id, headline, ad_type, publication, date_published, description,
                offer_details, price, price_label, contact_name, contact_phone, contact_email, status, source_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                g.tenant_id, org_id, headline, form.get("ad_type") or "Print",
                form.get("publication", "").strip() or None, form.get("date_published", "").strip() or None,
                form.get("description", "").strip() or None, form.get("offer_details", "").strip() or None,
                price, price_label,
                form.get("contact_name", "").strip() or None, form.get("contact_phone", "").strip() or None,
                form.get("contact_email", "").strip() or None, form.get("status") or "Active",
                form.get("source_notes", "").strip() or None,
            ),
        )
        db.commit()
        ad_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        if price is not None:
            db.execute(
                "INSERT INTO organization_ad_price_history (tenant_id, ad_listing_id, price, price_label, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (g.tenant_id, ad_id, price, price_label, "Initial price"),
            )
            db.commit()
        log_action("Create", "organization_ad_listing", ad_id, f"Created ad listing '{headline}'")
        flash("Ad listing created.", "success")
        return redirect(url_for("organizations.edit_ad", org_id=org_id, ad_id=ad_id))
    return render_template(
        "organizations/ad_form.html", org=org, ad=None, ad_types=AD_TYPES, price_history=[], notes=[], photos=[]
    )


@organizations_bp.route("/<int:org_id>/ads/<int:ad_id>/edit", methods=["GET", "POST"])
@login_required
def edit_ad(org_id, ad_id):
    db = get_db()
    org = _get_organization(db, org_id)
    ad = _get_ad_listing(db, org_id, ad_id)
    if request.method == "POST":
        form = request.form
        headline = form.get("headline", "").strip()
        if not headline:
            flash("Headline is required.", "error")
            return redirect(url_for("organizations.edit_ad", org_id=org_id, ad_id=ad_id))
        price = form.get("price", "").strip()
        try:
            price = float(price) if price else None
        except ValueError:
            price = None
        price_label = form.get("price_label", "").strip() or None
        if price is not None and ad["price"] is not None and price != ad["price"]:
            db.execute(
                "INSERT INTO organization_ad_price_history (tenant_id, ad_listing_id, price, price_label, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (g.tenant_id, ad_id, ad["price"], ad["price_label"], "Price before this edit"),
            )
        db.execute(
            """UPDATE organization_ad_listings SET headline=?, ad_type=?, publication=?, date_published=?,
               description=?, offer_details=?, price=?, price_label=?, contact_name=?, contact_phone=?,
               contact_email=?, status=?, source_notes=?, updated_at=datetime('now')
               WHERE ad_listing_id=? AND tenant_id=?""",
            (
                headline, form.get("ad_type") or "Print", form.get("publication", "").strip() or None,
                form.get("date_published", "").strip() or None, form.get("description", "").strip() or None,
                form.get("offer_details", "").strip() or None, price, price_label,
                form.get("contact_name", "").strip() or None, form.get("contact_phone", "").strip() or None,
                form.get("contact_email", "").strip() or None, form.get("status") or "Active",
                form.get("source_notes", "").strip() or None, ad_id, g.tenant_id,
            ),
        )
        db.commit()
        log_action("Update", "organization_ad_listing", ad_id, f"Updated ad listing '{headline}'")
        flash("Ad listing updated.", "success")
        return redirect(url_for("organizations.edit_ad", org_id=org_id, ad_id=ad_id))

    price_history = db.execute(
        "SELECT * FROM organization_ad_price_history WHERE ad_listing_id = ? AND tenant_id = ? ORDER BY recorded_at DESC",
        (ad_id, g.tenant_id),
    ).fetchall()
    notes = db.execute(
        "SELECT * FROM organization_ad_notes WHERE ad_listing_id = ? AND tenant_id = ? ORDER BY created_at DESC",
        (ad_id, g.tenant_id),
    ).fetchall()
    photos = db.execute(
        "SELECT * FROM organization_ad_photos WHERE ad_listing_id = ? AND tenant_id = ? ORDER BY created_at",
        (ad_id, g.tenant_id),
    ).fetchall()
    return render_template(
        "organizations/ad_form.html", org=org, ad=ad, ad_types=AD_TYPES,
        price_history=price_history, notes=notes, photos=photos,
    )


@organizations_bp.route("/<int:org_id>/ads/<int:ad_id>/delete", methods=["POST"])
@login_required
def delete_ad(org_id, ad_id):
    db = get_db()
    ad = _get_ad_listing(db, org_id, ad_id)
    for row in db.execute(
        "SELECT image_path FROM organization_ad_photos WHERE ad_listing_id = ? AND tenant_id = ?", (ad_id, g.tenant_id)
    ).fetchall():
        try:
            os.remove(os.path.join(Config.AD_PHOTOS_DIR, row["image_path"]))
        except OSError:
            pass
    db.execute("DELETE FROM organization_ad_photos WHERE ad_listing_id = ? AND tenant_id = ?", (ad_id, g.tenant_id))
    db.execute("DELETE FROM organization_ad_notes WHERE ad_listing_id = ? AND tenant_id = ?", (ad_id, g.tenant_id))
    db.execute("DELETE FROM organization_ad_price_history WHERE ad_listing_id = ? AND tenant_id = ?", (ad_id, g.tenant_id))
    db.execute("DELETE FROM organization_ad_listings WHERE ad_listing_id = ? AND tenant_id = ?", (ad_id, g.tenant_id))
    db.commit()
    log_action("Delete", "organization_ad_listing", ad_id, f"Deleted ad listing '{ad['headline']}'")
    flash("Ad listing deleted.", "success")
    return redirect(url_for("organizations.list_ads", org_id=org_id))


@organizations_bp.route("/<int:org_id>/ads/<int:ad_id>/notes/add", methods=["POST"])
@login_required
def add_ad_note(org_id, ad_id):
    db = get_db()
    _get_ad_listing(db, org_id, ad_id)
    note_text = request.form.get("note_text", "").strip()
    if note_text:
        db.execute(
            "INSERT INTO organization_ad_notes (tenant_id, ad_listing_id, note_text, source) VALUES (?, ?, ?, 'Manual')",
            (g.tenant_id, ad_id, note_text),
        )
        db.commit()
        log_action("Create", "organization_ad_note", ad_id, "Added note")
        flash("Note added.", "success")
    return redirect(url_for("organizations.edit_ad", org_id=org_id, ad_id=ad_id))


@organizations_bp.route("/<int:org_id>/ads/<int:ad_id>/photos/<int:photo_id>")
@login_required
def ad_photo(org_id, ad_id, photo_id):
    """Serves an Ad Listing's saved original-ad photo from disk (see
    Config.AD_PHOTOS_DIR) — used both for the on-screen gallery on the Edit
    Ad Listing page and by <a download> links to save a copy."""
    db = get_db()
    _get_ad_listing(db, org_id, ad_id)
    photo = db.execute(
        "SELECT * FROM organization_ad_photos WHERE ad_photo_id = ? AND ad_listing_id = ? AND tenant_id = ?",
        (photo_id, ad_id, g.tenant_id),
    ).fetchone()
    if photo is None:
        abort(404)
    return send_from_directory(Config.AD_PHOTOS_DIR, photo["image_path"])


@organizations_bp.route("/<int:org_id>/ads/<int:ad_id>/photos/<int:photo_id>/delete", methods=["POST"])
@login_required
def delete_ad_photo(org_id, ad_id, photo_id):
    db = get_db()
    _get_ad_listing(db, org_id, ad_id)
    photo = db.execute(
        "SELECT * FROM organization_ad_photos WHERE ad_photo_id = ? AND ad_listing_id = ? AND tenant_id = ?",
        (photo_id, ad_id, g.tenant_id),
    ).fetchone()
    if photo is None:
        abort(404)
    try:
        os.remove(os.path.join(Config.AD_PHOTOS_DIR, photo["image_path"]))
    except OSError:
        pass
    db.execute("DELETE FROM organization_ad_photos WHERE ad_photo_id = ? AND tenant_id = ?", (photo_id, g.tenant_id))
    db.commit()
    log_action("Delete", "organization_ad_photo", ad_id, f"Deleted ad photo #{photo_id}")
    flash("Photo removed.", "success")
    return redirect(url_for("organizations.edit_ad", org_id=org_id, ad_id=ad_id))


# ---- single-image import: extract -> human review/edit -> Save

@organizations_bp.route("/<int:org_id>/ads/import", methods=["GET"])
@login_required
def import_ad_form(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    return render_template("organizations/ad_import_form.html", org=org)


@organizations_bp.route("/<int:org_id>/ads/import/extract", methods=["POST"])
@login_required
def import_ad_extract(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    file = request.files.get("ad_image")
    if not file or not file.filename:
        flash("Please choose a photo of the ad.", "error")
        return redirect(url_for("organizations.import_ad_form", org_id=org_id))

    image_bytes = file.read()
    mime_type = file.mimetype or "image/jpeg"
    original_filename = file.filename

    try:
        ads = extract_ads_from_image(image_bytes, mime_type)
    except ExtractionError as e:
        flash(str(e), "error")
        return redirect(url_for("organizations.import_ad_form", org_id=org_id))

    ads_preview = []
    for item in ads:
        data = _ad_dict_from_extracted(item)
        existing = _find_ad_listing_by_headline(db, org_id, data["headline"])
        ads_preview.append({"data": data, "raw": item, "existing": existing})

    # The photo is held here, keyed by a random token, until Save — see
    # _pending_ad_path's docstring for why (same fix as the business-card
    # import's 413 bug: a full-size photo can't ride through the review
    # form as base64 in a hidden field).
    _cleanup_stale_pending_ads()
    ad_token = uuid.uuid4().hex
    _save_pending_ad_image(ad_token, image_bytes, mime_type)

    log_action(
        "Import", "organization_ad_listing", None,
        f"Extracted {len(ads_preview)} ad(s) from a photo for organization #{org_id}",
    )
    return render_template(
        "organizations/ad_import_review.html",
        org=org, ads=ads_preview, ad_token=ad_token, mime_type=mime_type,
        original_filename=original_filename, ad_types=AD_TYPES,
    )


@organizations_bp.route("/<int:org_id>/ads/import/pending/<token>")
@login_required
def pending_ad_image(org_id, token):
    """Serves the not-yet-saved ad photo for the review page's <img>
    preview, straight from the pending-ads holding directory — the review
    form itself only carries the token, not the image bytes (see
    import_ad_extract above)."""
    mime_type = request.args.get("mime") or "image/jpeg"
    path = _pending_ad_path(token, mime_type)
    if not path or not os.path.exists(path):
        abort(404)
    directory, filename = os.path.split(path)
    return send_from_directory(directory, filename)


@organizations_bp.route("/<int:org_id>/ads/import/save", methods=["POST"])
@login_required
def import_ad_save(org_id):
    db = get_db()
    _get_organization(db, org_id)
    form = request.form

    ad_token = form.get("ad_token") or ""
    mime_type = form.get("mime_type") or "image/jpeg"
    original_filename = form.get("original_filename") or None
    # The photo moves from the pending holding directory into the permanent
    # organization-ads uploads directory only now, at Save. If the
    # token/mime don't resolve to a file that still exists (e.g. this form
    # was already submitted once, or the pending copy aged out), the ad(s)
    # are still saved, just without a photo attached.
    pending_path = _pending_ad_path(ad_token, mime_type)
    photo_filename = _promote_pending_ad_image(pending_path) if pending_path and os.path.exists(pending_path) else None

    ad_count = int(form.get("ad_count") or 0)
    saved = []
    for i in range(ad_count):
        prefix = f"ad-{i}-"
        if not form.get(prefix + "include"):
            continue
        headline = form.get(prefix + "headline", "").strip()
        if not headline:
            continue
        price = form.get(prefix + "price", "").strip()
        try:
            price = float(price) if price else None
        except ValueError:
            price = None
        data = {
            "headline": headline,
            "ad_type": form.get(prefix + "ad_type") or "Other",
            "publication": form.get(prefix + "publication", "").strip() or None,
            "date_published": form.get(prefix + "date_published", "").strip() or None,
            "description": form.get(prefix + "description", "").strip() or None,
            "offer_details": form.get(prefix + "offer_details", "").strip() or None,
            "price": price,
            "price_label": form.get(prefix + "price_label", "").strip() or None,
            "contact_name": form.get(prefix + "contact_name", "").strip() or None,
            "contact_phone": form.get(prefix + "contact_phone", "").strip() or None,
            "contact_email": form.get(prefix + "contact_email", "").strip() or None,
        }

        existing = None
        existing_id = form.get(prefix + "existing_id") or None
        if existing_id:
            existing = db.execute(
                "SELECT * FROM organization_ad_listings WHERE ad_listing_id = ? AND organization_id = ? AND tenant_id = ?",
                (existing_id, org_id, g.tenant_id),
            ).fetchone()
        if not existing:
            existing = _find_ad_listing_by_headline(db, org_id, headline)

        source = original_filename or "Photo import"
        if existing:
            _update_ad_listing_partial(db, existing, data)
            ad_id = existing["ad_listing_id"]
            created = False
        else:
            ad_id = _create_ad_listing(db, org_id, data, source=source)
            created = True

        note_text = form.get(prefix + "source_notes", "").strip()
        if note_text:
            _add_ad_note(db, ad_id, note_text, source=source)

        if photo_filename:
            _attach_ad_photo_file(db, ad_id, photo_filename, mime_type, original_filename, source)

        db.commit()
        saved.append((ad_id, created))

    if not saved:
        flash("Nothing was saved — no ad had a headline, or every one was unchecked.", "error")
        return redirect(url_for("organizations.import_ad_form", org_id=org_id))

    new_count = sum(1 for _, created in saved if created)
    log_action(
        "Import", "organization_ad_listing", saved[0][0],
        f"Saved {len(saved)} ad(s) from photo import for organization #{org_id}",
    )
    flash(f"Saved {len(saved)} ad listing(s) ({new_count} new, {len(saved) - new_count} updated).", "success")
    return redirect(url_for("organizations.list_ads", org_id=org_id))


# ---- bulk zip import: extract + auto-save every ad found, no review step

@organizations_bp.route("/<int:org_id>/ads/import/batch", methods=["GET"])
@login_required
def import_ad_batch_form(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    return render_template("organizations/ad_import_batch_form.html", org=org, max_batch_images=MAX_BATCH_AD_IMAGES)


@organizations_bp.route("/<int:org_id>/ads/import/batch/extract", methods=["POST"])
@login_required
def import_ad_batch_extract(org_id):
    db = get_db()
    org = _get_organization(db, org_id)
    file = request.files.get("zip_file")
    if not file or not file.filename:
        flash("Please choose a zip file of ad photos.", "error")
        return redirect(url_for("organizations.import_ad_batch_form", org_id=org_id))

    zip_bytes = file.read()
    try:
        images = list(iter_images_from_zip(zip_bytes))
    except zipfile.BadZipFile:
        flash("That file isn't a valid zip archive.", "error")
        return redirect(url_for("organizations.import_ad_batch_form", org_id=org_id))

    if not images:
        flash("No recognizable image files (jpg/png/gif/webp) were found in that zip.", "error")
        return redirect(url_for("organizations.import_ad_batch_form", org_id=org_id))

    if len(images) > MAX_BATCH_AD_IMAGES:
        flash(
            f"That zip has {len(images)} images — the limit per batch is {MAX_BATCH_AD_IMAGES}. "
            f"Split it into smaller batches.",
            "error",
        )
        return redirect(url_for("organizations.import_ad_batch_form", org_id=org_id))

    results = []
    errors = []
    for filename, image_bytes, mime_type in images:
        try:
            ads = extract_ads_from_image(image_bytes, mime_type)
        except ExtractionError as e:
            errors.append({"filename": filename, "error": str(e)})
            continue
        try:
            photo_filename = _save_ad_photo_bytes(image_bytes, mime_type)
        except OSError as e:
            errors.append({"filename": filename, "error": f"Couldn't save the photo: {e}"})
            continue
        for item in ads:
            try:
                ad_id, was_update = _save_extracted_ad_item(
                    db, org_id, item, photo_filename, mime_type, filename, filename
                )
                ad_row = db.execute(
                    "SELECT headline FROM organization_ad_listings WHERE ad_listing_id = ?", (ad_id,)
                ).fetchone()
                results.append({
                    "ad_id": ad_id, "headline": ad_row["headline"], "was_update": was_update,
                    "filename": filename, "uncertain_fields": item.get("uncertain_fields") or [],
                })
            except Exception as e:
                errors.append({"filename": filename, "error": f"Couldn't save this ad: {e}"})

    log_action(
        "Import", "organization_ad_listing", None,
        f"Batch-imported ads for organization #{org_id}: {len(results)} saved, {len(errors)} error(s), "
        f"from {file.filename}",
    )
    return render_template("organizations/ad_import_batch_result.html", org=org, results=results, errors=errors)
