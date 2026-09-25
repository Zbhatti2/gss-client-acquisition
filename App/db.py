"""
SQLite connection management (Flask application-context pattern) and audit
logging helper. Deliberately plain sqlite3 — no ORM — schema.sql is the
single source of truth for structure.
"""
import sqlite3

import click
from flask import current_app, g, has_request_context, session

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

    Also callable from outside an HTTP request entirely -- e.g. a `flask`
    CLI command (see db.py's create-system-admin) -- where Flask's session
    doesn't exist at all; has_request_context() guards the lookup instead
    of blowing up with "Working outside of request context", and
    tenant_id/user_id just stay None (or whatever was passed) in that case.
    """
    if tenant_id is None and has_request_context():
        tenant_id = session.get("tenant_id")
    if user_id is None and has_request_context():
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


def next_account_number(db) -> int:
    """Consumes and returns the next tenant account number from the
    dedicated tenant_account_number_seq counter (schema.sql). This is the
    ONLY way an account_number should ever be assigned to a tenant -- never
    derived from MAX(account_number)+1 or from tenant_id, either of which
    would let a deleted tenant's number be handed to a different tenant
    later. The counter only ever increments, so a number is never repeated,
    regardless of what happens to the tenant that held it -- see
    tenants.account_number's comment in schema.sql for the business rule
    (a tenant with any activity can only be suspended, never deleted) this
    is built to support. Used by tenant_provisioning.py's provision_tenant()
    for every new tenant, and by the migrations below for the reserved GSS
    Platform row and for backfilling tenants created before this existed."""
    row = db.execute("SELECT next_value FROM tenant_account_number_seq WHERE id = 1").fetchone()
    value = row["next_value"]
    db.execute("UPDATE tenant_account_number_seq SET next_value = next_value + 1 WHERE id = 1")
    db.commit()
    return value


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


def _migration_tenant_address_and_rename(db):
    """Adds the tenant's own registered-address columns (see schema.sql's
    comment above tenants.address_street) and, one time only, corrects the
    seed tenant's placeholder name/address to the real business: GSS's
    seed-tenant flow originally shipped as "Acme Corp" with no address at
    all, standing in until the real company info was known. Keyed on
    tenant_code (a stable internal identifier, unlike tenant_name which is
    just the display text) rather than the current tenant_name, so this
    still finds the right row even if tenant_name had already been edited
    by hand in between. Runs once (tracked in schema_migrations like every
    migration here), so it will never overwrite a later, real rename."""
    for column, ddl in [
        ("address_street", "ALTER TABLE tenants ADD COLUMN address_street TEXT"),
        ("address_city", "ALTER TABLE tenants ADD COLUMN address_city TEXT"),
        ("address_state", "ALTER TABLE tenants ADD COLUMN address_state TEXT"),
        ("address_postal_code", "ALTER TABLE tenants ADD COLUMN address_postal_code TEXT"),
    ]:
        if not _column_exists(db, "tenants", column):
            db.execute(ddl)
    db.commit()

    db.execute(
        """UPDATE tenants SET
               tenant_name = 'Granite Signal Systems (GSS)',
               address_street = '104 Old Winslow Road',
               address_city = 'Wilmot',
               address_state = 'NH',
               address_postal_code = '03287',
               updated_at = datetime('now')
           WHERE tenant_code = 'ACME_CORP'"""
    )
    db.commit()


def _migration_agents_library(db):
    """Adds the Agents Library (see schema.sql's "MODULE AGENTS" comment):
    the global agents_library catalog, the per-tenant tenant_agents
    request/approval table, and the append-only agent_usage_log. Purely
    additive (new tables only), then seeds agents_library with the agents
    that already exist in code today (AI Business Card Import, AI Ad/
    Listing Import) — idempotent (INSERT OR IGNORE keyed on agent_code), so
    safe on a fresh install too."""
    for table, ddl in [
        ("agents_library", """
            CREATE TABLE agents_library (
                agent_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_code      TEXT NOT NULL UNIQUE,
                name            TEXT NOT NULL,
                description     TEXT,
                category        TEXT,
                sort_order      INTEGER DEFAULT 0,
                is_active       INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""),
        ("tenant_agents", """
            CREATE TABLE tenant_agents (
                tenant_agent_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                agent_id        INTEGER NOT NULL REFERENCES agents_library(agent_id),
                status          TEXT NOT NULL DEFAULT 'Requested' CHECK (status IN ('Requested','Approved','Denied','Revoked')),
                requested_by_user_id INTEGER REFERENCES users(user_id),
                requested_at    TEXT NOT NULL DEFAULT (datetime('now')),
                decided_by_user_id INTEGER REFERENCES users(user_id),
                decided_at      TEXT,
                notes           TEXT,
                UNIQUE (tenant_id, agent_id)
            )"""),
        ("agent_usage_log", """
            CREATE TABLE agent_usage_log (
                usage_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                agent_id        INTEGER NOT NULL REFERENCES agents_library(agent_id),
                user_id         INTEGER REFERENCES users(user_id),
                used_at         TEXT NOT NULL DEFAULT (datetime('now')),
                units           INTEGER NOT NULL DEFAULT 1,
                detail          TEXT
            )"""),
    ]:
        if not _table_exists(db, table):
            db.execute(ddl)
    db.commit()

    for name, idx_ddl in [
        ("idx_tenant_agents_tenant", "CREATE INDEX idx_tenant_agents_tenant ON tenant_agents(tenant_id)"),
        ("idx_tenant_agents_agent", "CREATE INDEX idx_tenant_agents_agent ON tenant_agents(agent_id)"),
        ("idx_agent_usage_log_tenant_agent", "CREATE INDEX idx_agent_usage_log_tenant_agent ON agent_usage_log(tenant_id, agent_id)"),
        ("idx_agent_usage_log_used_at", "CREATE INDEX idx_agent_usage_log_used_at ON agent_usage_log(used_at)"),
    ]:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name = ?", (name,)).fetchone():
            db.execute(idx_ddl)
    db.commit()

    from seed_data import seed_agents_library
    seed_agents_library(db)


# (master_table, fk_column, lookup_table, lookup_pk) — every relationship
# Table Maintenance manages (blueprints/table_maintenance.py TABLES, both
# its "references" and nested "parent" entries) plus the highest-value
# entity-level pickers. See schema.sql's "TENANT ISOLATION" comment for the
# full rationale; this Python list and that SQL block must be kept in sync
# by hand — this migration exists only to bring an already-existing
# installation's database up to date with what schema.sql now defines.
TENANT_FK_CHECKS = [
    ("contacts", "contact_category_id", "contact_categories", "contact_category_id"),
    ("contacts", "title_id", "contact_titles", "contact_title_id"),
    ("contacts", "suffix_id", "contact_suffixes", "contact_suffix_id"),
    ("contacts", "profession_id", "professions", "profession_id"),
    ("contacts", "context_id", "contact_contexts", "contact_context_id"),
    ("organizations", "organization_type_id", "organization_types", "organization_type_id"),
    ("organization_addresses", "address_type_id", "organization_address_types", "address_type_id"),
    ("organization_phones", "phone_type_id", "organization_phone_types", "phone_type_id"),
    ("content_knowledge_domains", "knowledge_domain_id", "knowledge_domains", "knowledge_domain_id"),
    ("content", "content_type_id", "content_types", "content_type_id"),
    ("content_contact_links", "link_type_id", "content_link_types", "content_link_type_id"),
    ("organizations", "size_category_id", "organization_size_categories", "size_category_id"),
    ("organizations", "organization_domain_id", "organization_domains", "organization_domain_id"),
    ("organizations", "organization_subdomain_id", "organization_subdomains", "organization_subdomain_id"),
    ("knowledge_subdomains", "knowledge_domain_id", "knowledge_domains", "knowledge_domain_id"),
    ("content_subtypes", "content_type_id", "content_types", "content_type_id"),
    ("organization_subdomains", "organization_domain_id", "organization_domains", "organization_domain_id"),
    ("contacts", "current_organization_id", "organizations", "organization_id"),
    ("contacts", "assistant_contact_id", "contacts", "contact_id"),
    ("content_contact_links", "contact_id", "contacts", "contact_id"),
]


def _migration_tenant_fk_triggers(db):
    """Creates the cross-tenant foreign-key guard triggers listed in
    TENANT_FK_CHECKS above (see schema.sql's "TENANT ISOLATION" comment for
    the rationale). CREATE TRIGGER IF NOT EXISTS makes each one safe to
    run twice, so this is a no-op against a freshly `init-db`'d database
    that already has them from schema.sql."""
    for master_table, fk_col, lookup_table, lookup_pk in TENANT_FK_CHECKS:
        msg = f"{master_table}.{fk_col}: cross-tenant reference not allowed"
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_tenant_fk_{master_table}_{fk_col}_ins
            BEFORE INSERT ON {master_table}
            WHEN NEW.{fk_col} IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, '{msg}')
                WHERE NOT EXISTS (
                    SELECT 1 FROM {lookup_table}
                    WHERE {lookup_pk} = NEW.{fk_col} AND tenant_id = NEW.tenant_id
                );
            END""")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_tenant_fk_{master_table}_{fk_col}_upd
            BEFORE UPDATE ON {master_table}
            WHEN NEW.{fk_col} IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, '{msg}')
                WHERE NOT EXISTS (
                    SELECT 1 FROM {lookup_table}
                    WHERE {lookup_pk} = NEW.{fk_col} AND tenant_id = NEW.tenant_id
                );
            END""")
    db.commit()


def _migration_tenant_drop_gss_suffix(db):
    """One-time cleanup: the first tenant originally shipped as "Granite
    Signal Systems (GSS)" (see _migration_tenant_address_and_rename above),
    which reads as if "GSS" were part of THIS tenant's own name. "GSS" is
    the platform's own name (the sidebar logo in templates/base.html), never
    a tenant's -- every tenant gets its own name at the tenant level, so the
    two are never in the same box. Strips the "(GSS)" suffix from that exact
    seeded value only; a tenant already renamed to something else by hand is
    left alone (matched on the old value, not on tenant_code, unlike that
    earlier migration)."""
    db.execute(
        """UPDATE tenants SET tenant_name = 'Granite Signal Systems', updated_at = datetime('now')
           WHERE tenant_code = 'ACME_CORP' AND tenant_name = 'Granite Signal Systems (GSS)'"""
    )
    db.commit()


def _migration_tenant_code_rename(db):
    """One-time cleanup: the first tenant's tenant_code was still the
    original 'ACME_CORP' placeholder slug (assigned before the real
    business name was known -- see _migration_tenant_address_and_rename),
    even after its tenant_name, address, and display had all been
    corrected to the real business. Renames it to 'GRANITSIG', a short code
    meaningful for THIS tenant (Granite Signal Systems), matching what every
    other tenant already gets automatically from tenant_provisioning.py's
    slugify_tenant_code() at creation. Matched on the exact old code, so a
    tenant_code already changed by hand in between is left alone -- same
    guard style as _migration_tenant_drop_gss_suffix just above.

    tenant_code remains purely an internal identifier (never shown to end
    users in the UI, and not used as a foreign key anywhere -- tenant_id is
    what every other table actually references). It is NOT a billing or
    account number: if GSS later wants a customer-facing, auto-generated,
    permanent account number for billing (a real ask, raised in
    conversation -- monotonically increasing, never reused even if a tenant
    is later deleted), that would be a separate new column with its own
    dedicated sequence, not a repurposing of this field. See this
    migration's neighboring comment in MIGRATIONS below for why: tenant_code
    is a short text slug chosen for readability, while an account number
    needs to be numeric, gap-free-in-intent, and generated with no human
    judgment involved -- two different jobs that don't belong on one
    column."""
    db.execute(
        "UPDATE tenants SET tenant_code = 'GRANITSIG', updated_at = datetime('now') "
        "WHERE tenant_code = 'ACME_CORP'"
    )
    db.commit()


def _migration_account_number_infra(db):
    """Adds tenants.account_number and is_platform, plus the dedicated
    tenant_account_number_seq counter table, to a database created before
    these existed. ALTER TABLE ADD COLUMN can't carry a UNIQUE constraint
    in SQLite (unlike a fresh CREATE TABLE, which schema.sql uses), so
    uniqueness is enforced with a separate index instead -- functionally
    identical, and tolerant of the transient NULLs every not-yet-backfilled
    existing tenant row will have until
    _migration_backfill_tenant_account_numbers runs right after this one
    (SQLite treats NULLs as distinct from each other under UNIQUE, so
    multiple NULL account_numbers don't collide)."""
    if not _column_exists(db, "tenants", "account_number"):
        db.execute("ALTER TABLE tenants ADD COLUMN account_number INTEGER")
    if not _column_exists(db, "tenants", "is_platform"):
        db.execute("ALTER TABLE tenants ADD COLUMN is_platform INTEGER NOT NULL DEFAULT 0")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_account_number ON tenants(account_number)")
    db.execute(
        """CREATE TABLE IF NOT EXISTS tenant_account_number_seq (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            next_value INTEGER NOT NULL
        )"""
    )
    db.execute("INSERT OR IGNORE INTO tenant_account_number_seq (id, next_value) VALUES (1, 10000001)")
    db.commit()


def _migration_create_platform_tenant(db):
    """Creates the single reserved "GSS Platform" tenant row (see
    schema.sql's tenants.is_platform comment) if it doesn't already exist,
    identified by tenant_code = 'GSS_PLATFORM'. This MUST run immediately
    after _migration_account_number_infra and immediately before
    _migration_backfill_tenant_account_numbers (see their order in
    MIGRATIONS below) so it is always the very first consumer of the
    account-number counter and always gets 10000001, with every real
    tenant (existing ones backfilled right after, and every new one from
    then on via provision_tenant()) landing at 10000002 or above.

    This row holds no users (nobody logs in as it -- it isn't a functional
    tenant) and needs a dek_wrapped only because the column is NOT NULL; a
    real DEK is generated for it like any other tenant even though nothing
    is expected to encrypt data under it today. It's excluded from Tenant
    Management's list and from toggle_status() (see blueprints/
    tenants_admin.py) via is_platform, not tenant_code, so those checks
    stay correct even if this code is ever renamed.

    What this row is FOR, concretely, is not built yet: the idea raised in
    conversation is for its own Table Maintenance-style lookup rows to
    become the master/reference data that new tenants clone at creation,
    replacing today's hardcoded seed_data.py constants and making that
    master data editable through the app instead of only in code. That
    needs its own follow-up work (a SystemAdmin-facing view of this
    tenant's lookup tables, and a change to seed_data.py's
    seed_lookup_tables() to copy from here instead) -- this migration only
    reserves the row and its account number so that follow-up has
    something to build on."""
    existing = db.execute("SELECT tenant_id FROM tenants WHERE tenant_code = 'GSS_PLATFORM'").fetchone()
    if existing:
        return

    from security import crypto

    dek = crypto.new_tenant_dek()
    dek_wrapped = crypto.wrap_tenant_dek(dek)
    account_number = next_account_number(db)
    db.execute(
        "INSERT INTO tenants (tenant_code, account_number, tenant_name, is_platform, dek_wrapped) "
        "VALUES ('GSS_PLATFORM', ?, 'GSS Platform', 1, ?)",
        (account_number, dek_wrapped),
    )
    db.commit()


def _migration_backfill_tenant_account_numbers(db):
    """Assigns an account_number to every tenant row that doesn't have one
    yet (every tenant created before this feature existed -- e.g. Granite
    Signal Systems). Ordered by tenant_id (creation order), so numbers come
    out in the same order tenants were actually created, same as any new
    tenant created from now on via provision_tenant(). Runs after
    _migration_create_platform_tenant, so 10000001 is already spoken for
    and the oldest real tenant lands on 10000002."""
    rows = db.execute(
        "SELECT tenant_id FROM tenants WHERE account_number IS NULL ORDER BY tenant_id ASC"
    ).fetchall()
    for row in rows:
        account_number = next_account_number(db)
        db.execute(
            "UPDATE tenants SET account_number = ?, updated_at = datetime('now') WHERE tenant_id = ?",
            (account_number, row["tenant_id"]),
        )
    db.commit()


def _migration_agents_billing(db):
    """Adds the Agents/Models/Billing layer on top of the existing Agents
    Library (see schema.sql's "MODULE AGENTS — AGENTS LIBRARY, MODELS &
    BILLING" comment, and the design doc
    claude/GSS_Agents_Billing_Architecture_v1.md in the project): the
    global ai_providers/ai_models/ai_model_rates catalog, agent_pricing_plans,
    tenant_model_credentials, plus new columns on the three tables the
    original Agents Library migration created (agents_library.tenant_id/
    default_model_id, tenant_agents.pricing_plan_id/subscribed_at,
    agent_usage_log.model_id/credential_id/tokens_input/tokens_output/
    actual_cost). Purely additive -- existing rows in agents_library/
    tenant_agents/agent_usage_log are untouched except for new NULL/default
    columns -- then seeds the model catalog, pricing plans for the two
    existing agents, and subscribes Granite Signal Systems (the first real
    tenant) to both as the first live test, exactly as schema.sql now
    defines for a fresh install too."""
    for table, ddl in [
        ("ai_providers", """
            CREATE TABLE ai_providers (
                provider_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_code   TEXT NOT NULL UNIQUE,
                name            TEXT NOT NULL,
                is_active       INTEGER NOT NULL DEFAULT 1
            )"""),
        ("ai_models", """
            CREATE TABLE ai_models (
                model_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_id     INTEGER NOT NULL REFERENCES ai_providers(provider_id),
                model_code      TEXT NOT NULL UNIQUE,
                display_name    TEXT NOT NULL,
                requires_tenant_api_key INTEGER NOT NULL DEFAULT 0,
                is_active       INTEGER NOT NULL DEFAULT 1,
                sort_order      INTEGER DEFAULT 0
            )"""),
        ("ai_model_rates", """
            CREATE TABLE ai_model_rates (
                rate_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id        INTEGER NOT NULL REFERENCES ai_models(model_id),
                effective_from  TEXT NOT NULL,
                cost_per_1k_input_tokens  REAL NOT NULL,
                cost_per_1k_output_tokens REAL NOT NULL,
                currency        TEXT NOT NULL DEFAULT 'USD'
            )"""),
        ("agent_pricing_plans", """
            CREATE TABLE agent_pricing_plans (
                plan_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id        INTEGER NOT NULL REFERENCES agents_library(agent_id),
                plan_code       TEXT NOT NULL,
                plan_name       TEXT NOT NULL,
                pricing_model   TEXT NOT NULL CHECK (pricing_model IN ('flat_monthly','per_transaction')),
                flat_fee_amount REAL,
                included_units_per_cycle INTEGER,
                overage_unit_fee REAL,
                per_transaction_fee REAL,
                required_model_id INTEGER REFERENCES ai_models(model_id),
                currency        TEXT NOT NULL DEFAULT 'USD',
                effective_from  TEXT NOT NULL DEFAULT (date('now')),
                effective_to    TEXT,
                is_active       INTEGER NOT NULL DEFAULT 1,
                UNIQUE (agent_id, plan_code)
            )"""),
        ("tenant_model_credentials", """
            CREATE TABLE tenant_model_credentials (
                credential_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                provider_id     INTEGER NOT NULL REFERENCES ai_providers(provider_id),
                api_key_wrapped BLOB NOT NULL,
                label           TEXT,
                added_by_user_id INTEGER REFERENCES users(user_id),
                added_at        TEXT NOT NULL DEFAULT (datetime('now')),
                is_active       INTEGER NOT NULL DEFAULT 1,
                last_used_at    TEXT,
                notes           TEXT
            )"""),
    ]:
        if not _table_exists(db, table):
            db.execute(ddl)
    db.commit()

    for column, ddl in [
        ("tenant_id", "ALTER TABLE agents_library ADD COLUMN tenant_id INTEGER REFERENCES tenants(tenant_id)"),
        ("default_model_id", "ALTER TABLE agents_library ADD COLUMN default_model_id INTEGER REFERENCES ai_models(model_id)"),
    ]:
        if not _column_exists(db, "agents_library", column):
            db.execute(ddl)
    for column, ddl in [
        ("pricing_plan_id", "ALTER TABLE tenant_agents ADD COLUMN pricing_plan_id INTEGER REFERENCES agent_pricing_plans(plan_id)"),
        ("subscribed_at", "ALTER TABLE tenant_agents ADD COLUMN subscribed_at TEXT"),
    ]:
        if not _column_exists(db, "tenant_agents", column):
            db.execute(ddl)
    for column, ddl in [
        ("model_id", "ALTER TABLE agent_usage_log ADD COLUMN model_id INTEGER REFERENCES ai_models(model_id)"),
        ("credential_id", "ALTER TABLE agent_usage_log ADD COLUMN credential_id INTEGER REFERENCES tenant_model_credentials(credential_id)"),
        ("tokens_input", "ALTER TABLE agent_usage_log ADD COLUMN tokens_input INTEGER"),
        ("tokens_output", "ALTER TABLE agent_usage_log ADD COLUMN tokens_output INTEGER"),
        ("actual_cost", "ALTER TABLE agent_usage_log ADD COLUMN actual_cost REAL"),
    ]:
        if not _column_exists(db, "agent_usage_log", column):
            db.execute(ddl)
    db.commit()

    for name, idx_ddl in [
        ("idx_ai_models_provider", "CREATE INDEX idx_ai_models_provider ON ai_models(provider_id)"),
        ("idx_ai_model_rates_model_effective", "CREATE INDEX idx_ai_model_rates_model_effective ON ai_model_rates(model_id, effective_from)"),
        ("idx_agents_library_tenant", "CREATE INDEX idx_agents_library_tenant ON agents_library(tenant_id)"),
        ("idx_agent_pricing_plans_agent", "CREATE INDEX idx_agent_pricing_plans_agent ON agent_pricing_plans(agent_id)"),
        ("idx_tenant_model_credentials_tenant", "CREATE INDEX idx_tenant_model_credentials_tenant ON tenant_model_credentials(tenant_id)"),
        ("idx_tenant_model_credentials_active", "CREATE UNIQUE INDEX idx_tenant_model_credentials_active ON tenant_model_credentials(tenant_id, provider_id) WHERE is_active = 1"),
    ]:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('index') AND name = ?", (name,)).fetchone():
            db.execute(idx_ddl)
    db.commit()

    from seed_data import seed_ai_catalog, seed_agent_pricing_plans, seed_granite_signal_billing_subscription
    seed_ai_catalog(db)
    seed_agent_pricing_plans(db)
    seed_granite_signal_billing_subscription(db)


# This module's own cross-tenant "picker" FK guards (see schema.sql's
# MODULE — CLIENT ACQUISITION section for the fresh-install versions of
# these same triggers, and its comment there on why this is a separate list
# rather than an addition to TENANT_FK_CHECKS above). Not consumed by
# _migration_tenant_fk_triggers -- _migration_client_acquisition_module
# below creates these itself, alongside the tables they guard.
CLIENT_ACQUISITION_TENANT_FK_CHECKS = [
    ("opportunities", "organization_id", "organizations", "organization_id"),
    ("opportunities", "pipeline_template_id", "pipeline_templates", "pipeline_template_id"),
    ("opportunities", "assigned_user_id", "users", "user_id"),
    ("opportunity_contacts", "contact_id", "contacts", "contact_id"),
    ("interactions", "contact_id", "contacts", "contact_id"),
    ("tasks", "assigned_user_id", "users", "user_id"),
]


def _migration_client_acquisition_module(db):
    """Adds the Client Acquisition (sales pipeline / CRM) module's 10 tables
    -- pipeline_templates, pipeline_template_stages, pipeline_template_
    checklist_items, pipeline_template_cadence_steps, opportunities,
    opportunity_contacts, opportunity_stage_checklist_progress, opportunity_
    stage_history, interactions, tasks -- to an already-existing database.
    See schema.sql's "MODULE — CLIENT ACQUISITION" section for the
    fresh-install versions of this exact same DDL, which this must be kept
    in sync with by hand (same convention as every other module here)."""
    for table, ddl in [
        ("pipeline_templates", """
            CREATE TABLE pipeline_templates (
                pipeline_template_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                template_name   TEXT NOT NULL,
                win_criteria_prompt TEXT,
                disqualify_after_days INTEGER,
                is_active       INTEGER NOT NULL DEFAULT 1,
                sort_order      INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(tenant_id, template_name)
            )"""),
        ("pipeline_template_stages", """
            CREATE TABLE pipeline_template_stages (
                stage_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                pipeline_template_id INTEGER NOT NULL REFERENCES pipeline_templates(pipeline_template_id),
                stage_number    INTEGER NOT NULL,
                stage_name      TEXT NOT NULL,
                typical_window_days INTEGER,
                probability_percent INTEGER NOT NULL DEFAULT 0 CHECK (probability_percent BETWEEN 0 AND 100),
                UNIQUE(pipeline_template_id, stage_number)
            )"""),
        ("pipeline_template_checklist_items", """
            CREATE TABLE pipeline_template_checklist_items (
                checklist_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                pipeline_template_id INTEGER NOT NULL REFERENCES pipeline_templates(pipeline_template_id),
                stage_number    INTEGER NOT NULL,
                item_label      TEXT NOT NULL,
                is_required     INTEGER NOT NULL DEFAULT 1,
                sort_order      INTEGER NOT NULL DEFAULT 0
            )"""),
        ("pipeline_template_cadence_steps", """
            CREATE TABLE pipeline_template_cadence_steps (
                cadence_step_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                pipeline_template_id INTEGER NOT NULL REFERENCES pipeline_templates(pipeline_template_id),
                stage_number    INTEGER NOT NULL,
                day_offset      INTEGER NOT NULL DEFAULT 0,
                action_label    TEXT NOT NULL,
                channel         TEXT CHECK (channel IN ('Call','Email','LinkedIn','Text','In-Person','Mail','Video','Note')),
                sort_order      INTEGER NOT NULL DEFAULT 0
            )"""),
        ("opportunities", """
            CREATE TABLE opportunities (
                opportunity_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),
                pipeline_template_id INTEGER NOT NULL REFERENCES pipeline_templates(pipeline_template_id),
                opportunity_name TEXT NOT NULL,
                assigned_user_id INTEGER REFERENCES users(user_id),
                status          TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Nurture','Lost','Closed')),
                current_stage_number INTEGER NOT NULL DEFAULT 1,
                stage_entered_date TEXT NOT NULL DEFAULT (datetime('now')),
                opportunity_value REAL,
                probability_percent INTEGER NOT NULL DEFAULT 0 CHECK (probability_percent BETWEEN 0 AND 100),
                lead_source     TEXT,
                lead_source_detail TEXT,
                disqualify_after_days INTEGER,
                next_action     TEXT,
                next_action_date TEXT,
                nurture_reason  TEXT CHECK (nurture_reason IN ('Timing','Budget Cycle','Internal Change','Rebrand','Hiring Freeze','Other')),
                nurture_revisit_date TEXT,
                lost_reason     TEXT CHECK (lost_reason IN ('Price','Competitor','Timing','No Budget','No Authority','No Need','Unresponsive','Out of Scope')),
                lost_date       TEXT,
                closed_date     TEXT,
                closed_won      INTEGER,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""),
        ("opportunity_contacts", """
            CREATE TABLE opportunity_contacts (
                opportunity_contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                opportunity_id  INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
                contact_id      INTEGER NOT NULL REFERENCES contacts(contact_id),
                contact_role    TEXT CHECK (contact_role IN ('Economic Buyer','Champion','Influencer','Blocker','Decision Maker','End User')),
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(opportunity_id, contact_id)
            )"""),
        ("opportunity_stage_checklist_progress", """
            CREATE TABLE opportunity_stage_checklist_progress (
                progress_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                opportunity_id  INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
                stage_number    INTEGER NOT NULL,
                item_label      TEXT NOT NULL,
                is_required     INTEGER NOT NULL DEFAULT 1,
                is_complete     INTEGER NOT NULL DEFAULT 0,
                completed_at    TEXT,
                completed_by_user_id INTEGER REFERENCES users(user_id),
                sort_order      INTEGER NOT NULL DEFAULT 0
            )"""),
        ("opportunity_stage_history", """
            CREATE TABLE opportunity_stage_history (
                stage_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                opportunity_id  INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
                from_status     TEXT,
                from_stage_number INTEGER,
                to_status       TEXT NOT NULL,
                to_stage_number INTEGER,
                from_probability_percent INTEGER,
                to_probability_percent INTEGER,
                is_manual_override INTEGER NOT NULL DEFAULT 0,
                reason          TEXT,
                changed_by_user_id INTEGER REFERENCES users(user_id),
                changed_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""),
        ("interactions", """
            CREATE TABLE interactions (
                interaction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                opportunity_id  INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
                contact_id      INTEGER REFERENCES contacts(contact_id),
                interaction_date TEXT NOT NULL DEFAULT (datetime('now')),
                channel         TEXT NOT NULL CHECK (channel IN ('Call','Email','LinkedIn','Text','In-Person','Mail','Video','Note')),
                direction       TEXT NOT NULL CHECK (direction IN ('Outbound','Inbound','Internal')),
                summary         TEXT,
                material_shared TEXT,
                outcome         TEXT CHECK (outcome IN (
                    'Connected','Left Voicemail','No Answer','Meeting Scheduled','Meeting Held',
                    'Proposal Sent','Follow-Up Needed','Referred Internally','Not Interested',
                    'Requested Callback','Gatekeeper','Wrong Contact','Rescheduled','Other'
                )),
                created_by_user_id INTEGER REFERENCES users(user_id),
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""),
        ("tasks", """
            CREATE TABLE tasks (
                task_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
                opportunity_id  INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
                assigned_user_id INTEGER REFERENCES users(user_id),
                title           TEXT NOT NULL,
                channel         TEXT CHECK (channel IN ('Call','Email','LinkedIn','Text','In-Person','Mail','Video','Note')),
                due_date        TEXT,
                source          TEXT NOT NULL DEFAULT 'Manual' CHECK (source IN ('Cadence','Manual','Nurture Revisit')),
                is_complete     INTEGER NOT NULL DEFAULT 0,
                completed_at    TEXT,
                created_at      TEXT NOT NULL DEFAULT (datetime('now'))
            )"""),
    ]:
        if not _table_exists(db, table):
            db.execute(ddl)
    db.commit()

    for name, idx_ddl in [
        ("idx_pipeline_templates_tenant", "CREATE INDEX idx_pipeline_templates_tenant ON pipeline_templates(tenant_id)"),
        ("idx_pipeline_template_stages_tenant", "CREATE INDEX idx_pipeline_template_stages_tenant ON pipeline_template_stages(tenant_id)"),
        ("idx_pipeline_template_stages_template", "CREATE INDEX idx_pipeline_template_stages_template ON pipeline_template_stages(pipeline_template_id)"),
        ("idx_pipeline_template_checklist_tenant", "CREATE INDEX idx_pipeline_template_checklist_tenant ON pipeline_template_checklist_items(tenant_id)"),
        ("idx_pipeline_template_checklist_template", "CREATE INDEX idx_pipeline_template_checklist_template ON pipeline_template_checklist_items(pipeline_template_id)"),
        ("idx_pipeline_template_cadence_tenant", "CREATE INDEX idx_pipeline_template_cadence_tenant ON pipeline_template_cadence_steps(tenant_id)"),
        ("idx_pipeline_template_cadence_template", "CREATE INDEX idx_pipeline_template_cadence_template ON pipeline_template_cadence_steps(pipeline_template_id)"),
        ("idx_opportunities_tenant", "CREATE INDEX idx_opportunities_tenant ON opportunities(tenant_id)"),
        ("idx_opportunities_organization", "CREATE INDEX idx_opportunities_organization ON opportunities(organization_id)"),
        ("idx_opportunities_template", "CREATE INDEX idx_opportunities_template ON opportunities(pipeline_template_id)"),
        ("idx_opportunities_assigned_user", "CREATE INDEX idx_opportunities_assigned_user ON opportunities(assigned_user_id)"),
        ("idx_opportunities_status", "CREATE INDEX idx_opportunities_status ON opportunities(status)"),
        ("idx_opportunity_contacts_tenant", "CREATE INDEX idx_opportunity_contacts_tenant ON opportunity_contacts(tenant_id)"),
        ("idx_opportunity_contacts_opportunity", "CREATE INDEX idx_opportunity_contacts_opportunity ON opportunity_contacts(opportunity_id)"),
        ("idx_opportunity_contacts_contact", "CREATE INDEX idx_opportunity_contacts_contact ON opportunity_contacts(contact_id)"),
        ("idx_opp_checklist_progress_tenant", "CREATE INDEX idx_opp_checklist_progress_tenant ON opportunity_stage_checklist_progress(tenant_id)"),
        ("idx_opp_checklist_progress_opportunity", "CREATE INDEX idx_opp_checklist_progress_opportunity ON opportunity_stage_checklist_progress(opportunity_id)"),
        ("idx_opp_stage_history_tenant", "CREATE INDEX idx_opp_stage_history_tenant ON opportunity_stage_history(tenant_id)"),
        ("idx_opp_stage_history_opportunity", "CREATE INDEX idx_opp_stage_history_opportunity ON opportunity_stage_history(opportunity_id)"),
        ("idx_interactions_tenant", "CREATE INDEX idx_interactions_tenant ON interactions(tenant_id)"),
        ("idx_interactions_opportunity", "CREATE INDEX idx_interactions_opportunity ON interactions(opportunity_id)"),
        ("idx_interactions_contact", "CREATE INDEX idx_interactions_contact ON interactions(contact_id)"),
        ("idx_tasks_tenant", "CREATE INDEX idx_tasks_tenant ON tasks(tenant_id)"),
        ("idx_tasks_opportunity", "CREATE INDEX idx_tasks_opportunity ON tasks(opportunity_id)"),
        ("idx_tasks_assigned_user", "CREATE INDEX idx_tasks_assigned_user ON tasks(assigned_user_id)"),
        ("idx_tasks_due_date", "CREATE INDEX idx_tasks_due_date ON tasks(due_date)"),
    ]:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)).fetchone():
            db.execute(idx_ddl)
    db.commit()

    for master_table, fk_col, lookup_table, lookup_pk in CLIENT_ACQUISITION_TENANT_FK_CHECKS:
        msg = f"{master_table}.{fk_col}: cross-tenant reference not allowed"
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_tenant_fk_{master_table}_{fk_col}_ins
            BEFORE INSERT ON {master_table}
            WHEN NEW.{fk_col} IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, '{msg}')
                WHERE NOT EXISTS (
                    SELECT 1 FROM {lookup_table}
                    WHERE {lookup_pk} = NEW.{fk_col} AND tenant_id = NEW.tenant_id
                );
            END""")
        db.execute(f"""CREATE TRIGGER IF NOT EXISTS trg_tenant_fk_{master_table}_{fk_col}_upd
            BEFORE UPDATE ON {master_table}
            WHEN NEW.{fk_col} IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, '{msg}')
                WHERE NOT EXISTS (
                    SELECT 1 FROM {lookup_table}
                    WHERE {lookup_pk} = NEW.{fk_col} AND tenant_id = NEW.tenant_id
                );
            END""")
    db.commit()

    # Seed pipeline templates onto the GSS_PLATFORM tenant and clone them
    # into every tenant that already exists (new tenants get this via
    # tenant_provisioning.py's provision_tenant() going forward). Safe to
    # call on a database with no platform templates yet -- both functions
    # are no-ops until seed_data.py actually defines PIPELINE_TEMPLATES.
    from seed_data import seed_platform_pipeline_templates, clone_pipeline_templates_to_tenant
    platform_row = db.execute("SELECT tenant_id FROM tenants WHERE tenant_code = 'GSS_PLATFORM'").fetchone()
    if platform_row:
        seed_platform_pipeline_templates(db, platform_row["tenant_id"])
        for row in db.execute("SELECT tenant_id FROM tenants WHERE is_platform = 0").fetchall():
            clone_pipeline_templates_to_tenant(db, platform_row["tenant_id"], row["tenant_id"])
    db.commit()


def _migration_lead_intake(db):
    """Adds tenants.lead_notification_email and tenants.lead_intake_token
    (see schema.sql's comment on these columns for what they're for --
    the public-website lead-capture-form integration in
    blueprints/public_leads.py). ALTER TABLE ADD COLUMN can't carry a
    UNIQUE constraint in SQLite, so uniqueness on lead_intake_token is
    enforced with a separate index instead, same approach as
    _migration_account_number_infra above.

    Every existing tenant is also backfilled with a freshly generated
    token here (secrets.token_urlsafe(32), the same generator auth/
    routes.py and security/csrf.py already use for bearer-style tokens)
    so lead intake can be turned on immediately via System Management's
    config screen without a separate "generate my first token" step --
    lead_notification_email stays NULL (opt-in: intake is inert for a
    tenant until a TenantAdmin sets a destination address)."""
    if not _column_exists(db, "tenants", "lead_notification_email"):
        db.execute("ALTER TABLE tenants ADD COLUMN lead_notification_email TEXT")
    if not _column_exists(db, "tenants", "lead_intake_token"):
        db.execute("ALTER TABLE tenants ADD COLUMN lead_intake_token TEXT")
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_lead_intake_token ON tenants(lead_intake_token)")
    db.commit()

    import secrets

    rows = db.execute("SELECT tenant_id FROM tenants WHERE lead_intake_token IS NULL").fetchall()
    for row in rows:
        db.execute(
            "UPDATE tenants SET lead_intake_token = ? WHERE tenant_id = ?",
            (secrets.token_urlsafe(32), row["tenant_id"]),
        )
    db.commit()


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
    ("2026_09_tenant_address_and_rename", _migration_tenant_address_and_rename),
    ("2026_09_agents_library", _migration_agents_library),
    ("2026_09_tenant_fk_triggers", _migration_tenant_fk_triggers),
    ("2026_09_tenant_drop_gss_suffix", _migration_tenant_drop_gss_suffix),
    ("2026_09_tenant_code_rename", _migration_tenant_code_rename),
    # Order matters for these three: infra (adds the columns + counter)
    # must run before the platform tenant is created, which must run
    # before backfilling existing tenants, so 10000001 always goes to the
    # platform row and 10000002 to the oldest real tenant.
    ("2026_09_account_number_infra", _migration_account_number_infra),
    ("2026_09_create_platform_tenant", _migration_create_platform_tenant),
    ("2026_09_backfill_tenant_account_numbers", _migration_backfill_tenant_account_numbers),
    ("2026_09_agents_billing", _migration_agents_billing),
    ("2026_09_client_acquisition_module", _migration_client_acquisition_module),
    ("2026_09_lead_intake", _migration_lead_intake),
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

    @app.cli.command("create-system-admin")
    @click.option("--username", prompt=True, help="Login id for the new SystemAdmin.")
    @click.option("--display-name", prompt="Display name", help="Shown in the UI (e.g. the person's real name).")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True,
                  help="Set interactively if omitted -- never pass this on the command line where it'd land in shell history.")
    def create_system_admin_command(username, display_name, password):
        """Flask CLI: `flask --app app create-system-admin` — creates a
        SystemAdmin login (the platform-wide, "GSS" level role -- Tenant
        Management, Agent Requests, Database Health/Backups). Unlike a
        TenantAdmin, a SystemAdmin belongs to no tenant (tenant_id is NULL
        -- see schema.sql MODULE T) and can't be created from inside the app
        by anyone, since there's no tenant-scoped screen for it and no
        existing SystemAdmin to grant the first one; this command is the
        one-time bootstrap for that first account. Run with no options to
        be prompted for everything, including the password (hidden,
        confirmed twice) -- never pass --password on the command line
        itself, where it would land in this machine's shell history."""
        from security.passwords import hash_password

        db = get_db()
        username = username.strip()
        if not username:
            click.echo("Username is required.")
            return
        if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            click.echo(f"A user with username {username!r} already exists (usernames are unique across the whole system).")
            return
        if len(password) < 8:
            click.echo("Password must be at least 8 characters.")
            return

        db.execute(
            "INSERT INTO users (tenant_id, username, display_name, password_hash, role) "
            "VALUES (NULL, ?, ?, ?, 'SystemAdmin')",
            (username, display_name.strip() or username, hash_password(password)),
        )
        db.commit()
        log_action("Create", "users", None, f"Created SystemAdmin {username!r} via CLI", tenant_id=None)
        click.echo(f"Created SystemAdmin {username!r}. Log in at /login with this username and password.")

    @app.cli.command("set-password")
    @click.option("--username", prompt=True, help="An existing user's login id (any role, any tenant).")
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True,
                  help="Set interactively if omitted -- never pass this on the command line in an interactive "
                       "shell, where it'd land in shell history (a fixed launcher .bat is a different, accepted "
                       "case -- see start_gss_*.bat).")
    def set_password_command(username, password):
        """Flask CLI: `flask --app app set-password` — (re)sets an
        EXISTING user's login password directly from the command line,
        bypassing both the in-app Reset Password flow (Manage Users,
        TenantAdmin-only, tenant-scoped) and the seed-phrase-based Forgot
        Password flow -- neither of which this command touches or
        replaces. Useful for a known launcher credential (see
        start_gss_sysadmin.bat / start_gss_tenant.bat, which call this on
        every start so their printed login always works) or recovering a
        locked-out account without either of those flows. Clears
        must_change_password, same as both of those flows already do,
        since setting someone's password IS that moment."""
        from security.passwords import hash_password

        db = get_db()
        username = username.strip()
        user = db.execute("SELECT user_id, tenant_id FROM users WHERE username = ?", (username,)).fetchone()
        if user is None:
            click.echo(f"No user with username {username!r}.")
            return
        if len(password) < 8:
            click.echo("Password must be at least 8 characters.")
            return

        db.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = datetime('now') "
            "WHERE user_id = ?",
            (hash_password(password), user["user_id"]),
        )
        db.commit()
        log_action("Update", "users", user["user_id"], f"Password set via CLI for {username!r}",
                   tenant_id=user["tenant_id"])
        click.echo(f"Password set for {username!r}.")
