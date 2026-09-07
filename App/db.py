"""
SQLite connection management (Flask application-context pattern) and audit
logging helper. Deliberately plain sqlite3 — no ORM — schema.sql is the
single source of truth for structure.
"""
import sqlite3

import click
from flask import current_app, g, session

from config import Config


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(Config.DATABASE_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with open(Config.SCHEMA_PATH, "r") as f:
        db.executescript(f.read())
    db.commit()


def log_action(action: str, entity_type: str = None, entity_id: int = None, detail: str = None,
                tenant_id: int = None, user_id: int = None):
    """Write one row to audit_log. Call this after any create/update/delete/
    import/export/login/purge — commits immediately so the audit trail
    survives even if the surrounding request later fails.

    tenant_id/user_id default to the current session's values when omitted,
    so most call sites inside a logged-in request don't need to pass them
    explicitly. Pass them explicitly for pre-login events (e.g. a failed
    login attempt, where the tenant may or may not be known yet).
    """
    if tenant_id is None:
        tenant_id = session.get("tenant_id")
    if user_id is None:
        user_id = session.get("user_id")
    db = get_db()
    db.execute(
        "INSERT INTO audit_log (tenant_id, user_id, action, entity_type, entity_id, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (tenant_id, user_id, action, entity_type, entity_id, detail),
    )
    db.commit()


def is_configured() -> bool:
    """Has at least one tenant been provisioned? GSS seeds the first tenant
    directly via seed_data.py, so in normal use this is already true by the
    time anyone hits the app; the /setup wizard (auth/routes.py) exists for
    provisioning additional tenants later and as a fallback if the database
    was created without seeding."""
    db = get_db()
    row = db.execute("SELECT 1 FROM tenants LIMIT 1").fetchone()
    return row is not None


# =============================================================================
# Schema migrations — additive, automatic, run once per new schema change.
#
# schema.sql is the source of truth for a BRAND NEW database (flask init-db).
# But a database someone is already using has to pick up later schema
# changes without losing data and without the person having to run any
# command themselves. MIGRATIONS below is the append-only list of those
# changes; run_pending_migrations() (called once at app startup — see
# app.py's create_app()) applies whichever of them this database hasn't
# seen yet, in order, and records each as done in schema_migrations so it's
# never re-applied. Every migration function must be safe to run twice (it
# guards its own CREATE/ALTER with an existence check) since it will also
# run, as a no-op, against a freshly `init-db`'d database that already has
# everything schema.sql now defines.
# =============================================================================

def _table_exists(db, table: str) -> bool:
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone() is not None


def _column_exists(db, table: str, column: str) -> bool:
    return any(row["name"] == column for row in db.execute(f"PRAGMA table_info({table})").fetchall())


def _migration_organization_domain_size(db):
    """Adds to Organizations: Number of Employees, Size Category, Domain,
    and SubDomain — three new tenant-scoped lookup tables
    (organization_size_categories, organization_domains,
    organization_subdomains, the last nested under domains) plus 4 new
    columns on organizations. Existing organizations rows are left with
    these columns NULL (unclassified) rather than guessed at."""
    if not _table_exists(db, "organization_size_categories"):
        db.execute("""CREATE TABLE organization_size_categories (
            size_category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
            code            TEXT,
            label           TEXT NOT NULL,
            description     TEXT,
            min_employees   INTEGER,
            max_employees   INTEGER,
            sort_order      INTEGER DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            UNIQUE (tenant_id, code)
        )""")
        db.execute("CREATE INDEX idx_organization_size_categories_tenant ON organization_size_categories(tenant_id)")

    if not _table_exists(db, "organization_domains"):
        db.execute("""CREATE TABLE organization_domains (
            organization_domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
            code            TEXT,
            label           TEXT NOT NULL,
            description     TEXT,
            sort_order      INTEGER DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            UNIQUE (tenant_id, code)
        )""")
        db.execute("CREATE INDEX idx_organization_domains_tenant ON organization_domains(tenant_id)")

    if not _table_exists(db, "organization_subdomains"):
        db.execute("""CREATE TABLE organization_subdomains (
            organization_subdomain_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
            organization_domain_id INTEGER NOT NULL REFERENCES organization_domains(organization_domain_id),
            code            TEXT,
            label           TEXT NOT NULL,
            description     TEXT,
            sort_order      INTEGER DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            UNIQUE (tenant_id, code)
        )""")
        db.execute("CREATE INDEX idx_organization_subdomains_tenant ON organization_subdomains(tenant_id)")
        db.execute("CREATE INDEX idx_organization_subdomains_domain ON organization_subdomains(organization_domain_id)")

    for column, ddl in [
        ("number_of_employees", "ALTER TABLE organizations ADD COLUMN number_of_employees INTEGER"),
        ("size_category_id", "ALTER TABLE organizations ADD COLUMN size_category_id INTEGER REFERENCES organization_size_categories(size_category_id)"),
        ("organization_domain_id", "ALTER TABLE organizations ADD COLUMN organization_domain_id INTEGER REFERENCES organization_domains(organization_domain_id)"),
        ("organization_subdomain_id", "ALTER TABLE organizations ADD COLUMN organization_subdomain_id INTEGER REFERENCES organization_subdomains(organization_subdomain_id)"),
    ]:
        if not _column_exists(db, "organizations", column):
            db.execute(ddl)

    db.commit()

    # Give every EXISTING tenant real Size Category / Domain / SubDomain
    # choices right away rather than empty dropdowns. Idempotent (INSERT OR
    # IGNORE keyed on (tenant_id, code)), so safe on a fresh install too.
    from seed_data import seed_organization_classification_lookups
    for row in db.execute("SELECT tenant_id FROM tenants").fetchall():
        seed_organization_classification_lookups(db, row["tenant_id"])
    db.commit()


def _migration_contact_business_card(db):
    """Adds Business Card (front/back image) to Contacts: two new nullable
    columns on contacts, plus a one-time sample record ("Gallant Plumbing
    Services") with both images attached so the feature is visibly
    demonstrated right away rather than landing as an empty, undiscovered
    field. Existing contacts are left with both columns NULL."""
    for column, ddl in [
        ("business_card_front_path", "ALTER TABLE contacts ADD COLUMN business_card_front_path TEXT"),
        ("business_card_back_path", "ALTER TABLE contacts ADD COLUMN business_card_back_path TEXT"),
    ]:
        if not _column_exists(db, "contacts", column):
            db.execute(ddl)
    db.commit()

    # Idempotent (checks for the sample contact by name first), so safe on
    # a fresh install too.
    from seed_data import seed_business_card_sample_contact
    for row in db.execute("SELECT tenant_id FROM tenants").fetchall():
        seed_business_card_sample_contact(db, row["tenant_id"])
    db.commit()


def _migration_organization_ad_listings(db):
    """Adds the Ad/Listing import feature for Organizations: organization_ad_listings
    plus its three child tables (price history, notes, photos) — see
    schema.sql's comment above organization_ad_listings for the full
    rationale. Purely additive (new tables only, nothing existing is
    touched), so this is a no-op on a database that doesn't have any
    Organizations yet and doesn't change a single existing row anywhere
    else."""
    for table, ddl in [
        ("organization_ad_listings", """
            CREATE TABLE organization_ad_listings (
                ad_listing_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),
                headline        TEXT NOT NULL,
                ad_type         TEXT NOT NULL DEFAULT 'Print' CHECK (ad_type IN ('Print','Online','Social Media','Classified','Direct Mail','Broadcast','Other')),
                publication     TEXT,
                date_published  TEXT,
                description     TEXT,
                offer_details   TEXT,
                price           REAL,
                price_label     TEXT,
                contact_name    TEXT,
                contact_phone   TEXT,
                contact_email   TEXT,
                status          TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Expired','Archived')),
                source          TEXT,
                source_notes    TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""),
        ("organization_ad_price_history", """
            CREATE TABLE organization_ad_price_history (
                ad_price_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                ad_listing_id   INTEGER NOT NULL REFERENCES organization_ad_listings(ad_listing_id),
                price           REAL NOT NULL,
                price_label     TEXT,
                effective_date  TEXT,
                recorded_at     TEXT NOT NULL DEFAULT (datetime('now')),
                note            TEXT
            )"""),
        ("organization_ad_notes", """
            CREATE TABLE organization_ad_notes (
                ad_note_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                ad_listing_id   INTEGER NOT NULL REFERENCES organization_ad_listings(ad_listing_id),
                note_text       TEXT NOT NULL,
                note_date       TEXT NOT NULL DEFAULT (date('now')),
                source          TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""),
        ("organization_ad_photos", """
            CREATE TABLE organization_ad_photos (
                ad_photo_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                ad_listing_id   INTEGER NOT NULL REFERENCES organization_ad_listings(ad_listing_id),
                image_path      TEXT NOT NULL,
                mime_type       TEXT NOT NULL DEFAULT 'image/jpeg',
                original_filename TEXT,
                caption         TEXT,
                source          TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""),
    ]:
        if not _table_exists(db, table):
            db.execute(ddl)
    db.commit()

    for name, idx_ddl in [
        ("idx_organization_ad_listings_tenant", "CREATE INDEX idx_organization_ad_listings_tenant ON organization_ad_listings(tenant_id)"),
        ("idx_organization_ad_listings_org", "CREATE INDEX idx_organization_ad_listings_org ON organization_ad_listings(organization_id)"),
        ("idx_organization_ad_price_history_listing", "CREATE INDEX idx_organization_ad_price_history_listing ON organization_ad_price_history(ad_listing_id)"),
        ("idx_organization_ad_notes_listing", "CREATE INDEX idx_organization_ad_notes_listing ON organization_ad_notes(ad_listing_id)"),
        ("idx_organization_ad_photos_listing", "CREATE INDEX idx_organization_ad_photos_listing ON organization_ad_photos(ad_listing_id)"),
    ]:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name = ?", (name,)).fetchone():
            db.execute(idx_ddl)
    db.commit()


def _migration_organization_main_fax(db):
    """Adds organizations.fax — the last of the four single-line "Main
    Address / Main Phone / Main Fax / Main Email" quick-contact fields (see
    schema.sql's comment above the organizations table). full_address/
    phone/email already existed on this table from GSS's PIMS-derived
    shape; fax is the one genuinely new column here. A plain nullable TEXT
    column, so this is a no-op on every existing row."""
    if not _column_exists(db, "organizations", "fax"):
        db.execute("ALTER TABLE organizations ADD COLUMN fax TEXT")
        db.commit()


def _migration_organization_main_address_parts(db):
    """Splits the Organization form's "Main Address" field from one
    free-text blob (full_address) into separate street/city/state/
    postal_code columns — see schema.sql's comment above the organizations
    table. Purely additive: full_address itself is untouched (Contacts'
    quick "add organization" form and the Organizations CSV importer still
    write to it directly), and every existing row's new columns start out
    NULL — there's no reliable way to auto-split old free-text addresses
    into parts, so nothing is guessed or backfilled here."""
    for column in ("street", "city", "state", "postal_code"):
        if not _column_exists(db, "organizations", column):
            db.execute(f"ALTER TABLE organizations ADD COLUMN {column} TEXT")
    db.commit()


def _migration_seed_us_cities(db):
    """Backfills the `cities` lookup (GLOBAL, no tenant_id) with real US
    city names for every state + DC — see seed_data.py's US_CITIES for the
    data and sourcing note. Purely additive data, no schema change: cities
    already existed as a table (Region -> Country -> Province/State ->
    City cascade used by the address forms' geography picker) but GSS
    shipped no seed cities out of the box, so every address's City field
    fell back to free text. Re-runs seed_global_lookups() as a whole
    rather than just the city rows — regions/countries/states/phone codes
    it also seeds are already present and INSERT OR IGNORE (or an
    equivalent existence check) makes those a no-op, so this only adds
    what's actually new."""
    from seed_data import seed_global_lookups
    seed_global_lookups(db)


# Append-only. Each entry is (unique_name, function(db)). Never edit or
# remove a past entry once shipped — a database that already applied it
# only cares that the name is still recorded in schema_migrations; add a
# new entry for any further change instead.
MIGRATIONS = [
    ("2026_09_organizations_domain_size", _migration_organization_domain_size),
    ("2026_09_contacts_business_card", _migration_contact_business_card),
    ("2026_09_organization_ad_listings", _migration_organization_ad_listings),
    ("2026_09_organization_main_fax", _migration_organization_main_fax),
    ("2026_09_organization_main_address_parts", _migration_organization_main_address_parts),
    ("2026_09_seed_us_cities", _migration_seed_us_cities),
]


def run_pending_migrations():
    """Applies whichever MIGRATIONS entries this database hasn't recorded
    yet, in order. Called once at app startup (app.py's create_app()), so
    an existing tenant's database is upgraded automatically the next time
    the app starts - no manual command, no data loss. A no-op, safely, on
    a database that isn't initialized yet (flask init-db hasn't run) or
    that already has every migration applied."""
    db = get_db()
    if not _table_exists(db, "tenants"):
        # Not initialized yet (e.g. this call came from `flask init-db`
        # itself, before the schema exists) - nothing to migrate onto.
        return
    db.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
        name TEXT PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    db.commit()
    applied = {row["name"] for row in db.execute("SELECT name FROM schema_migrations").fetchall()}
    for name, fn in MIGRATIONS:
        if name in applied:
            continue
        fn(db)
        db.execute("INSERT INTO schema_migrations (name) VALUES (?)", (name,))
        db.commit()


def init_app(app):
    app.teardown_appcontext(close_db)

    @app.cli.command("init-db")
    def init_db_command():
        """Flask CLI: `flask --app app init-db` — (re)creates all tables from schema.sql."""
        init_db()
        click.echo("Initialized the database from schema.sql.")

    @app.cli.command("seed-lookups")
    @click.argument("tenant_code")
    def seed_lookups_command(tenant_code):
        """Flask CLI: `flask --app app seed-lookups ACME` — populates
        MODULE E lookup tables for one tenant."""
        from seed_data import seed_lookup_tables

        db = get_db()
        row = db.execute("SELECT tenant_id FROM tenants WHERE tenant_code = ?", (tenant_code,)).fetchone()
        if row is None:
            click.echo(f"No tenant with code {tenant_code!r}. Run `flask --app app seed-tenant` first.")
            return
        seed_lookup_tables(db, row["tenant_id"])
        click.echo(f"Seeded lookup tables for tenant {tenant_code}.")

    @app.cli.command("seed-tenant")
    def seed_tenant_command():
        """Flask CLI: `flask --app app seed-tenant` — creates the first
        tenant with its Tenant Admin, plus that tenant's lookup tables.
        Safe to re-run; does nothing if the tenant already exists."""
        from seed_data import seed_first_tenant

        db = get_db()
        seed_first_tenant(db)
        click.echo("Seeded the first tenant and its admin user.")
