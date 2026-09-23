"""
Module — Geography Maintenance. Lets a Tenant Admin add/edit/deactivate/
delete rows in the four GLOBAL geography tables — regions, countries,
states (Province/State), cities — the same way Table Maintenance does for
tenant-scoped lookup tables, but as its own top-level module under
Utilities rather than nested inside Table Maintenance (see app.py's
MODULES) — these four tables are shared property across every tenant, not
a per-tenant picklist, so they get their own place in the nav and a
stricter access level (tenant_admin_required, not just login_required).

Adapted from the Tourism Management System's blueprints/geography_admin.py
(same architecture GSS's whole dev stack follows) with one correctness fix
for GSS's own schema: TMS's own version only lists `addresses` (Contacts)
in each table's "references" for usage-counting/delete-protection, because
that's the only address table TMS had wired to the geography cascade at
the time. GSS also has `organization_addresses` pointing at
region_id/country_id/state_id/city_id (see schema.sql), so every entry
below lists both — otherwise deleting a city still used only by an
organization's address would wrongly report "Unused", and the delete
would then fail with an unhandled sqlite3.IntegrityError instead of the
friendly "still used by N records" message.

The key difference from table_maintenance.py: these four tables have NO
tenant_id column at all. They're shared across every tenant (see
schema.sql's geography comment), so an edit made here — a relabel, a
merge, a delete — is visible to, and affects, every tenant, not just the
one the editing admin belongs to.

The four tables also form a strict hierarchy — Region -> Country ->
Province/State -> City — so each (except Regions, the top) has a required
"parent" picker on its add/edit form, same single-level "parent" mechanic
table_maintenance.py already uses for organization_subdomains. Unlike
table_maintenance's tenant-scoped lookups (usually a couple dozen rows),
Countries alone has 241 rows and Cities has 3,000+, so the list view here
also supports a free-text search box and, where a table has a parent, a
"filter to just this parent" dropdown (e.g. only California's cities).

Column shape isn't identical across all four tables — cities has no `code`
or `description` column, regions has no `description` — so each entry in
TABLES below declares has_code/has_description and the shared helpers
build INSERT/UPDATE column lists from that instead of assuming every
lookup table has the same five columns.
"""
import sqlite3

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from auth.decorators import tenant_admin_required
from db import get_db, log_action

geography_admin_bp = Blueprint("geography_admin", __name__)


# "references" lists every table (including a table's own children, one
# level down the hierarchy — e.g. a country's children are its states) that
# stores a foreign key into this table; used both to count usage before a
# delete and to bulk-reassign rows during a merge. Deleting a country that
# still has states under it, or an address pointing at it (Contact or
# Organization), is blocked the same way table_maintenance blocks deleting
# an in-use lookup entry.
TABLES = {
    "regions": {
        "label": "Regions",
        "table": "regions",
        "pk": "region_id",
        "has_code": True,
        "has_description": False,
        "references": [
            {"table": "countries", "fk": "region_id", "label": "countr(y/ies)"},
            {"table": "addresses", "fk": "region_id", "label": "contact address(es)"},
            {"table": "organization_addresses", "fk": "region_id", "label": "organization address(es)"},
        ],
    },
    "countries": {
        "label": "Countries",
        "table": "countries",
        "pk": "country_id",
        "has_code": True,
        "has_description": True,
        "parent": {
            "table": "regions", "pk": "region_id", "fk": "region_id",
            "label_field": "label", "nav_label": "Region",
        },
        "references": [
            {"table": "states", "fk": "country_id", "label": "province/state(s)"},
            {"table": "addresses", "fk": "country_id", "label": "contact address(es)"},
            {"table": "organization_addresses", "fk": "country_id", "label": "organization address(es)"},
            {"table": "country_phone_codes", "fk": "country_id", "label": "phone code(s)"},
        ],
    },
    "states": {
        "label": "Provinces / States",
        "table": "states",
        "pk": "state_id",
        "has_code": True,
        "has_description": True,
        "parent": {
            "table": "countries", "pk": "country_id", "fk": "country_id",
            "label_field": "label", "nav_label": "Country",
        },
        "references": [
            {"table": "cities", "fk": "state_id", "label": "cit(y/ies)"},
            {"table": "addresses", "fk": "state_id", "label": "contact address(es)"},
            {"table": "organization_addresses", "fk": "state_id", "label": "organization address(es)"},
        ],
    },
    "cities": {
        "label": "Cities",
        "table": "cities",
        "pk": "city_id",
        "has_code": False,
        "has_description": False,
        "parent": {
            "table": "states", "pk": "state_id", "fk": "state_id",
            "label_field": "label", "nav_label": "Province/State",
        },
        "references": [
            {"table": "addresses", "fk": "city_id", "label": "contact address(es)"},
            {"table": "organization_addresses", "fk": "city_id", "label": "organization address(es)"},
        ],
    },
}


def _table_config(table_key):
    cfg = TABLES.get(table_key)
    if cfg is None:
        abort(404)
    return cfg


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _usage_count(db, cfg, entry_id):
    """Total rows across every referencing table (children one level down
    the hierarchy, plus Contact/Organization addresses/country_phone_codes)
    that point at this row, plus a per-table breakdown for display. No
    tenant filter — these are global tables, so usage is counted across
    every tenant."""
    total = 0
    breakdown = []
    for ref in cfg["references"]:
        count = db.execute(
            f"SELECT COUNT(*) c FROM {ref['table']} WHERE {ref['fk']} = ?", (entry_id,)
        ).fetchone()["c"]
        if count:
            breakdown.append({"label": ref["label"], "count": count})
        total += count
    return total, breakdown


def _parent_options(db, cfg):
    """Active rows from a table's parent lookup, for the picker on its
    add/edit form (and the filter dropdown on its list). None when the
    table is Regions, the top of the hierarchy."""
    p = cfg.get("parent")
    if not p:
        return None
    return db.execute(
        f"SELECT * FROM {p['table']} WHERE is_active = 1 ORDER BY {p['label_field']} COLLATE NOCASE"
    ).fetchall()


def _row_values(form, cfg):
    """Column -> value for an insert/update, built from the submitted form
    and this table's actual column shape (cities has neither code nor
    description; regions has no description)."""
    label = form.get("label", "").strip()
    values = {
        "label": label,
        "sort_order": _safe_int(form.get("sort_order"), 0),
        "is_active": 1 if form.get("is_active") else 0,
    }
    if cfg.get("has_code", True):
        values["code"] = form.get("code", "").strip() or None
    if cfg.get("has_description", True):
        values["description"] = form.get("description", "").strip() or None
    if cfg.get("parent"):
        values[cfg["parent"]["fk"]] = _safe_int(form.get("parent_id"), None)
    return label, values


@geography_admin_bp.route("/")
@tenant_admin_required
def index():
    db = get_db()
    tables = []
    for key, cfg in TABLES.items():
        total = db.execute(f"SELECT COUNT(*) c FROM {cfg['table']}").fetchone()["c"]
        active = db.execute(f"SELECT COUNT(*) c FROM {cfg['table']} WHERE is_active = 1").fetchone()["c"]
        tables.append({"key": key, "cfg": cfg, "total": total, "active": active})
    return render_template("geography_admin/index.html", tables=tables)


@geography_admin_bp.route("/<table_key>")
@tenant_admin_required
def manage(table_key):
    cfg = _table_config(table_key)
    db = get_db()
    q = request.args.get("q", "").strip()
    parent_filter = request.args.get("parent_id", "").strip()

    select_cols = "t.*"
    joins = ""
    where = []
    params = []
    if cfg.get("parent"):
        p = cfg["parent"]
        select_cols += f", p.{p['label_field']} AS parent_label"
        joins += f" LEFT JOIN {p['table']} p ON p.{p['pk']} = t.{p['fk']}"
        if parent_filter:
            where.append(f"t.{p['fk']} = ?")
            params.append(parent_filter)
    if q:
        like = f"%{q}%"
        if cfg.get("has_code", True):
            where.append("(t.label LIKE ? OR t.code LIKE ?)")
            params.extend([like, like])
        else:
            where.append("t.label LIKE ?")
            params.append(like)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    # Alphabetical by Label, same as every dropdown/picker elsewhere in the
    # app that lists these geography lookups (see contacts.py) — so a
    # freshly added entry takes its place immediately instead of sitting
    # wherever sort_order's default of 0 puts it (see table_maintenance.py's
    # matching comment for the tenant-scoped lookup tables).
    order = (
        f"p.{cfg['parent']['label_field']} COLLATE NOCASE, t.label COLLATE NOCASE"
        if cfg.get("parent") else "t.label COLLATE NOCASE"
    )
    sql = f"SELECT {select_cols} FROM {cfg['table']} t{joins}{where_sql} ORDER BY {order}"
    rows = db.execute(sql, params).fetchall()

    entries = [{"row": r, "usage_count": _usage_count(db, cfg, r[cfg["pk"]])[0]} for r in rows]
    return render_template(
        "geography_admin/manage.html", table_key=table_key, cfg=cfg, entries=entries,
        q=q, parent_filter=parent_filter, parent_options=_parent_options(db, cfg),
    )


@geography_admin_bp.route("/<table_key>/new", methods=["GET", "POST"])
@tenant_admin_required
def new_entry(table_key):
    cfg = _table_config(table_key)
    db = get_db()
    if request.method == "POST":
        form = request.form
        label, values = _row_values(form, cfg)
        if not label:
            flash("Label is required.", "error")
            return render_template("geography_admin/form.html", cfg=cfg, table_key=table_key, entry=None, parent_options=_parent_options(db, cfg))
        if cfg.get("parent") and not values[cfg["parent"]["fk"]]:
            flash(f"{cfg['parent']['nav_label']} is required.", "error")
            return render_template("geography_admin/form.html", cfg=cfg, table_key=table_key, entry=None, parent_options=_parent_options(db, cfg))
        try:
            cols = ", ".join(values.keys())
            qs = ", ".join(["?"] * len(values))
            db.execute(f"INSERT INTO {cfg['table']} ({cols}) VALUES ({qs})", tuple(values.values()))
            db.commit()
        except sqlite3.IntegrityError:
            flash("That conflicts with an existing entry in this table (duplicate code, or duplicate name within the same parent) — codes and names must be unique there.", "error")
            return render_template("geography_admin/form.html", cfg=cfg, table_key=table_key, entry=None, parent_options=_parent_options(db, cfg))

        new_id = db.execute("SELECT last_insert_rowid() id").fetchone()["id"]
        log_action("Create", cfg["table"], new_id, f"Added {cfg['label']} entry '{label}' (global geography table)")
        flash(f"'{label}' added.", "success")
        return redirect(url_for("geography_admin.manage", table_key=table_key))
    return render_template("geography_admin/form.html", cfg=cfg, table_key=table_key, entry=None, parent_options=_parent_options(db, cfg))


@geography_admin_bp.route("/<table_key>/<int:entry_id>/edit", methods=["GET", "POST"])
@tenant_admin_required
def edit_entry(table_key, entry_id):
    cfg = _table_config(table_key)
    db = get_db()
    entry = db.execute(f"SELECT * FROM {cfg['table']} WHERE {cfg['pk']} = ?", (entry_id,)).fetchone()
    if entry is None:
        abort(404)
    if request.method == "POST":
        form = request.form
        label, values = _row_values(form, cfg)
        if not label:
            flash("Label is required.", "error")
            return render_template("geography_admin/form.html", cfg=cfg, table_key=table_key, entry=entry, parent_options=_parent_options(db, cfg))
        if cfg.get("parent") and not values[cfg["parent"]["fk"]]:
            flash(f"{cfg['parent']['nav_label']} is required.", "error")
            return render_template("geography_admin/form.html", cfg=cfg, table_key=table_key, entry=entry, parent_options=_parent_options(db, cfg))
        try:
            set_clause = ", ".join(f"{col}=?" for col in values.keys())
            db.execute(f"UPDATE {cfg['table']} SET {set_clause} WHERE {cfg['pk']}=?", tuple(values.values()) + (entry_id,))
            db.commit()
        except sqlite3.IntegrityError:
            flash("That conflicts with an existing entry in this table (duplicate code, or duplicate name within the same parent) — codes and names must be unique there.", "error")
            return render_template("geography_admin/form.html", cfg=cfg, table_key=table_key, entry=entry, parent_options=_parent_options(db, cfg))

        log_action("Update", cfg["table"], entry_id, f"Updated {cfg['label']} entry '{label}' (global geography table)")
        flash(f"'{label}' updated — anywhere it's already used (across every tenant) will show the new text right away.", "success")
        return redirect(url_for("geography_admin.manage", table_key=table_key))
    return render_template("geography_admin/form.html", cfg=cfg, table_key=table_key, entry=entry, parent_options=_parent_options(db, cfg))


@geography_admin_bp.route("/<table_key>/<int:entry_id>/toggle-active", methods=["POST"])
@tenant_admin_required
def toggle_active(table_key, entry_id):
    cfg = _table_config(table_key)
    db = get_db()
    entry = db.execute(f"SELECT * FROM {cfg['table']} WHERE {cfg['pk']} = ?", (entry_id,)).fetchone()
    if entry is None:
        abort(404)
    new_state = 0 if entry["is_active"] else 1
    db.execute(f"UPDATE {cfg['table']} SET is_active = ? WHERE {cfg['pk']} = ?", (new_state, entry_id))
    db.commit()
    log_action("Update", cfg["table"], entry_id, f"{'Activated' if new_state else 'Deactivated'} '{entry['label']}' (global geography table)")
    flash(f"'{entry['label']}' {'activated' if new_state else 'deactivated'}.", "success")
    return redirect(url_for("geography_admin.manage", table_key=table_key))


@geography_admin_bp.route("/<table_key>/<int:entry_id>/delete", methods=["POST"])
@tenant_admin_required
def delete_entry(table_key, entry_id):
    cfg = _table_config(table_key)
    db = get_db()
    entry = db.execute(f"SELECT * FROM {cfg['table']} WHERE {cfg['pk']} = ?", (entry_id,)).fetchone()
    if entry is None:
        abort(404)
    count, _ = _usage_count(db, cfg, entry_id)
    if count > 0:
        flash(
            f"'{entry['label']}' is still used by {count} record(s) (possibly across more than one tenant), "
            f"so it can't be deleted outright. Deactivate it, or reassign those records to a different entry first.",
            "error",
        )
        return redirect(url_for("geography_admin.reassign", table_key=table_key, entry_id=entry_id))
    db.execute(f"DELETE FROM {cfg['table']} WHERE {cfg['pk']} = ?", (entry_id,))
    db.commit()
    log_action("Delete", cfg["table"], entry_id, f"Deleted unused {cfg['label']} entry '{entry['label']}' (global geography table)")
    flash(f"'{entry['label']}' deleted.", "success")
    return redirect(url_for("geography_admin.manage", table_key=table_key))


@geography_admin_bp.route("/<table_key>/<int:entry_id>/reassign", methods=["GET", "POST"])
@tenant_admin_required
def reassign(table_key, entry_id):
    """Bulk-move every record that references `entry_id` (children one
    level down the hierarchy, plus Contact/Organization addresses/
    country_phone_codes — across EVERY tenant, since these tables are
    global) over to a different entry in the same table, then optionally
    delete the old entry. Reached either from a blocked delete, or directly
    from the manage list as a standalone "merge into..." action — this is
    also how two near-duplicate entries (e.g. a CSV import's "Saint Louis"
    vs. the seeded "St. Louis") could be merged by hand later if desired."""
    cfg = _table_config(table_key)
    db = get_db()
    entry = db.execute(f"SELECT * FROM {cfg['table']} WHERE {cfg['pk']} = ?", (entry_id,)).fetchone()
    if entry is None:
        abort(404)
    count, breakdown = _usage_count(db, cfg, entry_id)
    others = db.execute(
        f"SELECT * FROM {cfg['table']} WHERE {cfg['pk']} != ? ORDER BY label COLLATE NOCASE", (entry_id,)
    ).fetchall()

    if request.method == "POST":
        target_id = _safe_int(request.form.get("target_id"), None)
        also_delete = bool(request.form.get("also_delete"))
        if not target_id:
            flash("Choose an entry to reassign these records to.", "error")
            return redirect(url_for("geography_admin.reassign", table_key=table_key, entry_id=entry_id))
        target = db.execute(f"SELECT * FROM {cfg['table']} WHERE {cfg['pk']} = ?", (target_id,)).fetchone()
        if target is None:
            abort(404)

        moved = 0
        for ref in cfg["references"]:
            cur = db.execute(f"UPDATE {ref['table']} SET {ref['fk']} = ? WHERE {ref['fk']} = ?", (target_id, entry_id))
            moved += cur.rowcount

        if also_delete:
            db.execute(f"DELETE FROM {cfg['table']} WHERE {cfg['pk']} = ?", (entry_id,))
        db.commit()

        log_action(
            "Update", cfg["table"], entry_id,
            f"Reassigned {moved} record(s) from '{entry['label']}' to '{target['label']}' (global geography table)"
            + (" and deleted the old entry" if also_delete else ""),
        )
        flash(
            f"Moved {moved} record(s) from '{entry['label']}' to '{target['label']}'."
            + (
                f" '{entry['label']}' was then deleted."
                if also_delete
                else f" '{entry['label']}' is still in the list with nothing pointing at it — deactivate or delete it separately whenever you like."
            ),
            "success",
        )
        return redirect(url_for("geography_admin.manage", table_key=table_key))

    return render_template(
        "geography_admin/reassign.html",
        cfg=cfg, table_key=table_key, entry=entry, others=others,
        usage_count=count, usage_breakdown=breakdown,
    )
