-- ============================================================================
-- GSS — Granite Signal Systems Client Acquisition Maximizing Platform
-- Data Model, Draft v1
--
-- PROVENANCE
--   * Data model CLONED from PIMS (Personal Information Management System,
--     Phase 1) at D:\Codegen\Claude\PIMS, per the GSS project brief.
--   * Multi-tenancy / multi-user architecture CLONED from Tourism Management
--     System (TMS) Phase 1.1 at D:\Codegen\Claude\Tourism Management System —
--     TMS is itself PIMS reworked for multi-tenancy, so this draft applies
--     that same rework directly to PIMS's modules rather than re-deriving it.
--   * SQLite, no ORM (plain sqlite3 via db.py) — same convention as both
--     source projects.
--
-- SCOPE — GSS's six modules per the project brief:
--   Organizations | Contacts | Documents & Knowledge Base | Data Exchange |
--   Table Maintenance | System Management
--
-- EXCLUDED FROM THE PIMS CLONE
--   * Module B — Platforms & Subscriptions (cloud_platforms,
--     cloud_service_subscriptions, desktop_software_licenses, and their
--     child/history tables) — excluded per explicit project brief instruction.
--   * The `service_types` lookup table ("Services" in PIMS) — excluded per
--     the same instruction. It existed only to classify cloud_platforms, so
--     dropping Platforms & Subscriptions makes it unused in any case.
--   * Module C — Personal Accounts (personal_accounts, its history table,
--     personal_account_types) — ASSUMPTION: not excluded by name in the
--     brief's NOTE, but also not one of GSS's six listed modules, so left out
--     of this draft. Flag if GSS actually needs a comparable
--     accounts/credentials module — it would follow the same encrypted-field
--     pattern as the fields below.
--   * `software_types` lookup — only used by desktop_software_licenses
--     (Platforms & Subscriptions), dropped for the same reason as
--     service_types.
--   * Tourism-only material from TMS (Points of Interest, Suppliers, Human
--     Resources, Organization Intelligence, Inventory/Services/Products,
--     Package Management, Knowledge Graph) — none of this came from PIMS in
--     the first place; it was TMS's own Phase 1.2+ build-out, not part of
--     what GSS is cloning.
--
-- CARRIED OVER FROM TMS (the multi-tenancy rework, applied here to PIMS's
-- modules exactly as TMS applied it to its own):
--   * MODULE T (tenants/users/roles) — verbatim.
--   * Every tenant-owned table gets its own `tenant_id` column, so any query
--     filters with a plain `WHERE tenant_id = ?`.
--   * `countries`, `states`, `country_phone_codes` stay GLOBAL (shared,
--     real-world geography). TMS additionally introduced `regions` (a Region
--     tier above Country) and `cities` (a City tier below State) with a full
--     Region -> Country -> State -> City cascade on every address; this
--     draft keeps that enrichment since it is a strict improvement on PIMS's
--     flat country/state pair and GSS is a fresh clone, not a compatibility
--     migration.
--   * Every other lookup table is tenant-scoped (own `tenant_id`, `UNIQUE
--     (tenant_id, code)`) so each org using GSS maintains its own picklists
--     via Table Maintenance without affecting other tenants.
--   * Field encryption is per-TENANT (`tenants.dek_wrapped`), not derived
--     from any one user's password — see MODULE T comment block below.
--   * PIMS's standalone `system_config` table (single-user password/DEK
--     wrapping) is gone, same as in TMS — its job is split between
--     `tenants` (dek_wrapped, data_retention_days) and `users`
--     (password_hash, recovery_seed_hash), since encryption is per-tenant
--     and login is per-user.
--
-- ENRICHED FROM TMS BEYOND PIMS'S ORIGINAL SHAPE (kept here because GSS
-- names Organizations as a first-class module in its own right, not just an
-- attribute of Contacts):
--   * PIMS's `organizations` had flat full_address/phone/email text columns.
--     TMS added `organization_addresses`, `organization_emails`,
--     `organization_phones` (each multi-valued, own type lookups) — the same
--     multi-value/history pattern already used for Contacts. This draft
--     keeps TMS's richer shape; the original flat columns are kept
--     alongside (as TMS did) purely as a legacy fallback, unused by the UI.
--
-- OPEN QUESTIONS FOR REVIEW (see accompanying decisions doc):
--   1. Personal Accounts (Module C) — include or not? (excluded above)
--   2. Organizations' new address/phone/email tables — TMS gates deletion
--      history off for these (Organizations = reference data, not an
--      audited record the way a Contact is). Confirm that's right for GSS
--      too, where Organizations are prospects/clients being pursued for
--      acquisition — arguably MORE deserving of a history trail than a
--      tourism supplier directory entry was.
--   3. Table Maintenance has no schema of its own here — it is a blueprint
--      (generic CRUD UI) over every tenant-scoped lookup table below, same
--      as in TMS. Confirm no additional "meta" table (e.g. a registry of
--      which lookup tables are Table-Maintenance-editable) is wanted.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ============================================================================
-- MODULE T — TENANTS & USERS (multi-tenant, multi-user login)
--
-- PIMS (single-user) tied its one master password directly to unwrapping the
-- field-encryption DEK (Data Encryption Key) — a clever trick for one person
-- on one machine, but it does not extend to "N users who all need to read
-- the same tenant's data." For GSS, authentication and field encryption are
-- deliberately split, exactly as TMS did it:
--
--   * users.password_hash — a standard salted hash (werkzeug/scrypt via
--     security/passwords.py), checked normally at login. Any user of a
--     tenant logs in with their own password; nothing about the tenant's
--     encrypted data depends on which password was used.
--   * tenants.dek_wrapped — each tenant gets its own random DEK, used to
--     encrypt that tenant's sensitive columns. The DEK is wrapped under a
--     single system-level master key (instance/tenant_master.key — see
--     config.py), and unwrapped by the server itself once a user's password
--     check succeeds. It is never derived from any user's password.
--
-- Roles:
--   * SystemAdmin — provisions new tenants, runs whole-database backups.
--     Not scoped to any one tenant (tenant_id is NULL).
--   * TenantAdmin — manages users and data within their own tenant (their
--     own client-acquisition org).
--   * User        — regular day-to-day user within their own tenant.
-- ============================================================================

CREATE TABLE tenants (
    tenant_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_code     TEXT NOT NULL UNIQUE,    -- short slug, e.g. 'ACME' — internal identifier (exports, future subdomains), not shown as "the" name to end users
    tenant_name     TEXT NOT NULL,           -- display name, e.g. 'Acme Corp'
    status          TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Suspended')),
    dek_wrapped     BLOB NOT NULL,           -- Fernet(system tenant-master-key).encrypt(tenant DEK) — see security/crypto.py + config.get_tenant_master_key()
    data_retention_days INTEGER DEFAULT NULL, -- days from a record's date of entry (created_at) until purge-eligible; NULL = indefinite (never auto-purge). Per-tenant.
    last_purge_at   TEXT,                    -- last time this tenant's purge check actually ran (once/day, checked at login), regardless of whether anything was purged
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER REFERENCES tenants(tenant_id),   -- NULL only for SystemAdmin (see CHECK below)
    username        TEXT NOT NULL UNIQUE,    -- globally unique login id, so login needs no tenant picker
    display_name    TEXT NOT NULL,
    email           TEXT,
    password_hash   TEXT NOT NULL,           -- werkzeug/scrypt password hash — standard auth, independent of field encryption (see MODULE T note above)
    role            TEXT NOT NULL DEFAULT 'User' CHECK (role IN ('SystemAdmin','TenantAdmin','User')),
    recovery_seed_hash TEXT,                 -- SHA-256 of this user's normalized recovery seed phrase, for self-service "forgot password"
    is_active       INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    last_login_at   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK ( (role = 'SystemAdmin' AND tenant_id IS NULL) OR (role IN ('TenantAdmin','User') AND tenant_id IS NOT NULL) )
);
CREATE INDEX idx_users_tenant ON users(tenant_id);

-- ============================================================================
-- MODULE E — SYSTEM TABLES (lookup / reference data)
-- ============================================================================

-- GLOBAL — shared across every tenant (real-world geography, not tenant
-- opinion). Top tier of the geography hierarchy: Region -> Country ->
-- Province/State -> City. (Region/City tiers are TMS's enrichment over
-- PIMS's flat Country/State pair — kept here, see header note.)
CREATE TABLE regions (
    region_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    code            TEXT UNIQUE,            -- e.g. 'NA'
    label           TEXT NOT NULL,          -- e.g. 'North America'
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1
);

-- GLOBAL.
CREATE TABLE countries (
    country_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    region_id       INTEGER REFERENCES regions(region_id),
    code            TEXT UNIQUE,            -- ISO 3166-1 alpha-2, e.g. 'US'
    label           TEXT NOT NULL,          -- display name, e.g. 'United States'
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_countries_region ON countries(region_id);

-- GLOBAL. `label` is always the full name (e.g. 'New York', never just
-- 'NY'), so display is consistent everywhere — countries whose provinces
-- have no standard code simply leave `code` NULL.
CREATE TABLE states (
    state_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    country_id      INTEGER NOT NULL REFERENCES countries(country_id),
    code            TEXT,                   -- e.g. 'NY'; NULL where the country's provinces have no code
    label           TEXT NOT NULL,          -- e.g. 'New York'
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_states_country ON states(country_id);
CREATE UNIQUE INDEX idx_states_country_code ON states(country_id, code) WHERE code IS NOT NULL;

-- GLOBAL. Bottom tier of the geography hierarchy.
CREATE TABLE cities (
    city_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    state_id        INTEGER NOT NULL REFERENCES states(state_id),
    label           TEXT NOT NULL,          -- e.g. 'Buffalo'
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_cities_state ON cities(state_id);
CREATE UNIQUE INDEX idx_cities_state_label ON cities(state_id, label);

-- GLOBAL.
CREATE TABLE country_phone_codes (
    country_phone_code_id INTEGER PRIMARY KEY AUTOINCREMENT,
    country_id      INTEGER NOT NULL REFERENCES countries(country_id),
    calling_code    TEXT NOT NULL,          -- e.g. '+1'
    label           TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_country_phone_codes_country ON country_phone_codes(country_id);

-- Tenant-scoped lookup tables below: each tenant maintains its own list via
-- Table Maintenance. `code` uniqueness is per-tenant, not global.

CREATE TABLE contact_categories (
    contact_category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_contact_categories_tenant ON contact_categories(tenant_id);

CREATE TABLE contact_titles (
    contact_title_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_contact_titles_tenant ON contact_titles(tenant_id);

CREATE TABLE contact_suffixes (
    contact_suffix_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_contact_suffixes_tenant ON contact_suffixes(tenant_id);

CREATE TABLE professions (
    profession_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_professions_tenant ON professions(tenant_id);

CREATE TABLE contact_contexts (
    contact_context_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_contact_contexts_tenant ON contact_contexts(tenant_id);

CREATE TABLE organization_types (
    organization_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_organization_types_tenant ON organization_types(tenant_id);

-- Lookup for organization_addresses.address_type_id (below) — an
-- organization's several address locations (Mailing Address, Physical
-- Address, ...).
CREATE TABLE organization_address_types (
    address_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_organization_address_types_tenant ON organization_address_types(tenant_id);

-- Lookup for organization_phones.phone_type_id (below) — an organization's
-- several phone numbers (Office, Mobile, Fax, ...).
CREATE TABLE organization_phone_types (
    phone_type_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_organization_phone_types_tenant ON organization_phone_types(tenant_id);

CREATE TABLE knowledge_domains (
    knowledge_domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_knowledge_domains_tenant ON knowledge_domains(tenant_id);

-- One level of nesting under knowledge_domains (e.g. domain "Technology" ->
-- sub-domains "AI/ML", "Cybersecurity"). Added via Table Maintenance.
CREATE TABLE knowledge_subdomains (
    knowledge_subdomain_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    knowledge_domain_id INTEGER NOT NULL REFERENCES knowledge_domains(knowledge_domain_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_knowledge_subdomains_tenant ON knowledge_subdomains(tenant_id);
CREATE INDEX idx_knowledge_subdomains_domain ON knowledge_subdomains(knowledge_domain_id);

CREATE TABLE content_types (
    content_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_content_types_tenant ON content_types(tenant_id);

-- One level of nesting under content_types (e.g. type "Article" -> sub-types
-- "Blog Post", "White Paper"). Added via Table Maintenance.
CREATE TABLE content_subtypes (
    content_subtype_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    content_type_id INTEGER NOT NULL REFERENCES content_types(content_type_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_content_subtypes_tenant ON content_subtypes(tenant_id);
CREATE INDEX idx_content_subtypes_type ON content_subtypes(content_type_id);

-- Lookup for content_contact_links.link_type_id (Module D below) — e.g.
-- "Author", "Reviewed by".
CREATE TABLE content_link_types (
    content_link_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_content_link_types_tenant ON content_link_types(tenant_id);

-- ============================================================================
-- SHARED — polymorphic addresses (used by Module A Contacts). Organizations
-- use their own dedicated organization_addresses table below instead (see
-- MODULE A header note) — 'Contact' is the only owner_type GSS needs, since
-- Personal Accounts (PIMS Module C, the other historical owner_type) is out
-- of scope here.
-- ============================================================================

CREATE TABLE addresses (
    address_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    owner_type      TEXT NOT NULL CHECK (owner_type IN ('Contact')),
    owner_id        INTEGER NOT NULL,       -- FK into contacts.contact_id
    address_type    TEXT,                   -- Home / Business / Billing / On Account, etc.
    street          TEXT,
    unit            TEXT,
    region_id       INTEGER REFERENCES regions(region_id),      -- geography cascade: Region -> Country -> Province/State -> City
    country_id      INTEGER REFERENCES countries(country_id),
    state_id        INTEGER REFERENCES states(state_id),        -- picked from the states lookup, once country is chosen
    state_province_text TEXT,                                   -- free-text fallback, only used if the country's provinces aren't seeded in the states lookup
    city_id         INTEGER REFERENCES cities(city_id),          -- picked from the cities lookup, once province/state is chosen
    city_text       TEXT,                                        -- free-text fallback, only used if the province's cities aren't seeded in the cities lookup
    postal_code     TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_addresses_tenant ON addresses(tenant_id);
CREATE INDEX idx_addresses_owner ON addresses(owner_type, owner_id);

-- address_id is deliberately NOT a foreign key into addresses(address_id): a
-- "Deleted" history row is written right before the live addresses row is
-- removed, so a hard FK here would make that delete permanently impossible.
-- previous_value already holds a full snapshot.
CREATE TABLE addresses_history (
    address_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    address_id      INTEGER NOT NULL,
    owner_type      TEXT NOT NULL,
    owner_id        INTEGER NOT NULL,
    field_name      TEXT,
    previous_value  TEXT,                   -- JSON snapshot of the superseded address
    superseded_at   TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_reason TEXT
);
CREATE INDEX idx_addresses_history_tenant ON addresses_history(tenant_id);
CREATE INDEX idx_addresses_history_address ON addresses_history(address_id);

-- ============================================================================
-- MODULE — ORGANIZATIONS
--
-- GSS names Organizations as a first-class module in its own right (not just
-- an attribute of Contacts, as it effectively was in PIMS). This draft keeps
-- TMS's enrichment over PIMS's flat organizations shape: dedicated,
-- multi-valued organization_addresses / organization_emails /
-- organization_phones tables (own type lookups above), rather than the
-- single free-text full_address/phone/email columns PIMS had. The legacy
-- flat columns are kept on `organizations` itself, unused by the UI, purely
-- so nothing is silently dropped if old PIMS-shaped data is ever imported.
-- ============================================================================

CREATE TABLE organizations (
    organization_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    organization_name TEXT NOT NULL,
    full_address    TEXT,                   -- legacy flat fallback — see module note above; superseded by organization_addresses
    phone           TEXT,                   -- legacy flat fallback — superseded by organization_phones
    email           TEXT,                   -- legacy flat fallback — superseded by organization_emails
    website         TEXT,
    organization_type_id INTEGER REFERENCES organization_types(organization_type_id),
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_organizations_tenant ON organizations(tenant_id);

CREATE TABLE organization_addresses (
    organization_address_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),
    address_type_id INTEGER REFERENCES organization_address_types(address_type_id),
    street          TEXT,
    unit            TEXT,
    region_id       INTEGER REFERENCES regions(region_id),
    country_id      INTEGER REFERENCES countries(country_id),
    state_id        INTEGER REFERENCES states(state_id),
    state_province_text TEXT,               -- free-text fallback, same convention as addresses
    city_id         INTEGER REFERENCES cities(city_id),
    city_text       TEXT,                   -- free-text fallback, same convention as addresses
    postal_code     TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_organization_addresses_tenant ON organization_addresses(tenant_id);
CREATE INDEX idx_organization_addresses_org ON organization_addresses(organization_id);
CREATE INDEX idx_organization_addresses_type ON organization_addresses(address_type_id);

CREATE TABLE organization_emails (
    organization_email_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),
    email_address   TEXT NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_organization_emails_tenant ON organization_emails(tenant_id);
CREATE INDEX idx_organization_emails_org ON organization_emails(organization_id);

CREATE TABLE organization_phones (
    organization_phone_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),
    phone_type_id   INTEGER REFERENCES organization_phone_types(phone_type_id),
    country_code    TEXT,                   -- e.g. '+1'
    area_code       TEXT,
    number          TEXT NOT NULL,
    extension       TEXT,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_organization_phones_tenant ON organization_phones(tenant_id);
CREATE INDEX idx_organization_phones_org ON organization_phones(organization_id);
CREATE INDEX idx_organization_phones_type ON organization_phones(phone_type_id);

-- Reference-links list on an Organization's own page (a web URL and/or a
-- local document path, each with a short description/notes) — the lighter
-- per-record link list, distinct from the Module D document library.
CREATE TABLE organization_reference_links (
    link_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),
    url             TEXT,
    document_path   TEXT,                   -- local drive path/name
    description     TEXT,
    notes           TEXT,                   -- brief summary; web URLs are auto-linked on display
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_organization_reference_links_tenant ON organization_reference_links(tenant_id);
CREATE INDEX idx_organization_reference_links_org ON organization_reference_links(organization_id);

-- ============================================================================
-- MODULE — CONTACTS (has all contacts of an Organization)
-- ============================================================================

CREATE TABLE contacts (
    contact_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    title_id        INTEGER REFERENCES contact_titles(contact_title_id),
    full_name       TEXT NOT NULL,
    suffix_id       INTEGER REFERENCES contact_suffixes(contact_suffix_id),
    gender          TEXT,                    -- 'Male' | 'Female' | 'Other' — fixed list, not a lookup table
    file_as         TEXT,
    current_organization_id INTEGER REFERENCES organizations(organization_id),
    current_job_title TEXT,
    profession_id   INTEGER REFERENCES professions(profession_id),
    web_page        TEXT,
    contact_category_id INTEGER REFERENCES contact_categories(contact_category_id),
    context_id      INTEGER REFERENCES contact_contexts(contact_context_id),
    assistant_contact_id INTEGER REFERENCES contacts(contact_id),  -- self-referential: another contact who acts as this one's assistant
    priority_contact INTEGER NOT NULL DEFAULT 0,
    profile_image_path TEXT,
    date_of_birth   TEXT,
    is_deceased     INTEGER NOT NULL DEFAULT 0,
    date_of_death   TEXT,                   -- only meaningful when is_deceased = 1; cleared otherwise
    notes           TEXT,
    knowledge_graph_data TEXT,              -- freeform, ';'-delimited entries (e.g. "Reports to X"); Phase 2: structured triples
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_contacts_tenant ON contacts(tenant_id);
CREATE INDEX idx_contacts_category ON contacts(contact_category_id);
CREATE INDEX idx_contacts_organization ON contacts(current_organization_id);

CREATE TABLE contacts_history (
    contact_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    contact_id      INTEGER NOT NULL REFERENCES contacts(contact_id),
    field_name      TEXT NOT NULL,          -- 'current_organization_id' or 'current_job_title'
    previous_value  TEXT,
    superseded_at   TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_reason TEXT
);
CREATE INDEX idx_contacts_history_tenant ON contacts_history(tenant_id);
CREATE INDEX idx_contacts_history_contact ON contacts_history(contact_id);

CREATE TABLE contact_emails (
    email_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    contact_id      INTEGER NOT NULL REFERENCES contacts(contact_id),
    email_address   TEXT NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_contact_emails_tenant ON contact_emails(tenant_id);
CREATE INDEX idx_contact_emails_contact ON contact_emails(contact_id);

-- email_id is deliberately NOT a foreign key into contact_emails(email_id)
-- — a "Deleted" history row is inserted right before the live row it
-- describes is removed.
CREATE TABLE contact_emails_history (
    email_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    email_id        INTEGER NOT NULL,
    contact_id      INTEGER NOT NULL,
    previous_value  TEXT,
    superseded_at   TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_reason TEXT
);
CREATE INDEX idx_contact_emails_history_tenant ON contact_emails_history(tenant_id);

CREATE TABLE contact_phones (
    phone_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    contact_id      INTEGER NOT NULL REFERENCES contacts(contact_id),
    phone_type      TEXT NOT NULL CHECK (phone_type IN ('Business','Home','Mobile','WhatsApp','Business Fax')),
    country_code    TEXT,                   -- e.g. '+1'
    area_code       TEXT,
    number          TEXT NOT NULL,
    extension       TEXT,                   -- business numbers only
    is_primary      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_contact_phones_tenant ON contact_phones(tenant_id);
CREATE INDEX idx_contact_phones_contact ON contact_phones(contact_id);

-- phone_id is deliberately NOT a foreign key into contact_phones(phone_id)
-- — same reason as contact_emails_history above.
CREATE TABLE contact_phones_history (
    phone_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    phone_id        INTEGER NOT NULL,
    contact_id      INTEGER NOT NULL,
    previous_value  TEXT,                   -- JSON snapshot (type/country/area/number/ext)
    superseded_at   TEXT NOT NULL DEFAULT (datetime('now')),
    superseded_reason TEXT
);
CREATE INDEX idx_contact_phones_history_tenant ON contact_phones_history(tenant_id);

CREATE TABLE contact_reference_links (
    link_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    contact_id      INTEGER NOT NULL REFERENCES contacts(contact_id),
    url             TEXT,
    document_path   TEXT,                   -- local drive path/name
    description     TEXT,
    notes           TEXT,                   -- brief summary; web URLs are auto-linked on display
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_contact_reference_links_tenant ON contact_reference_links(tenant_id);
CREATE INDEX idx_contact_reference_links_contact ON contact_reference_links(contact_id);

-- Archive table (soft-delete target). Mirrors the live shape plus deletion
-- bookkeeping. Child rows are cascaded into the JSON snapshot rather than
-- archived row-by-row, to keep the purge job simple.
CREATE TABLE contacts_archive (
    contact_id      INTEGER PRIMARY KEY,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    snapshot        TEXT NOT NULL,          -- full JSON snapshot of the contact + children
    deleted_at      TEXT NOT NULL DEFAULT (datetime('now')),
    purge_eligible_at TEXT
);
CREATE INDEX idx_contacts_archive_tenant ON contacts_archive(tenant_id);

-- ============================================================================
-- MODULE — DOCUMENTS & KNOWLEDGE BASE
-- ============================================================================

CREATE TABLE content (
    content_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    content_name    TEXT NOT NULL,
    content_type_id INTEGER REFERENCES content_types(content_type_id),
    authors         TEXT,
    description     TEXT,
    notes           TEXT,                    -- brief summary; web URLs are auto-linked on display
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_content_tenant ON content(tenant_id);

CREATE TABLE content_locations (
    location_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    content_id      INTEGER NOT NULL REFERENCES content(content_id),
    location_type   TEXT CHECK (location_type IN ('Cloud Link','Local Drive Path')),
    path_or_url     TEXT NOT NULL
);
CREATE INDEX idx_content_locations_tenant ON content_locations(tenant_id);
CREATE INDEX idx_content_locations_content ON content_locations(content_id);

CREATE TABLE content_knowledge_domains (
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    content_id      INTEGER NOT NULL REFERENCES content(content_id),
    knowledge_domain_id INTEGER NOT NULL REFERENCES knowledge_domains(knowledge_domain_id),
    PRIMARY KEY (content_id, knowledge_domain_id)
);
CREATE INDEX idx_content_knowledge_domains_tenant ON content_knowledge_domains(tenant_id);

CREATE TABLE content_keywords (
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    content_id      INTEGER NOT NULL REFERENCES content(content_id),
    term            TEXT NOT NULL,
    PRIMARY KEY (content_id, term)
);
CREATE INDEX idx_content_keywords_tenant ON content_keywords(tenant_id);

CREATE TABLE content_hashtags (
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    content_id      INTEGER NOT NULL REFERENCES content(content_id),
    term            TEXT NOT NULL,
    PRIMARY KEY (content_id, term)
);
CREATE INDEX idx_content_hashtags_tenant ON content_hashtags(tenant_id);

-- "Contacts Link" on the Content form — lets a content item reference an
-- existing Contact, a plain URL, or both, optionally tagged with a Link Type
-- (e.g. "Author", "Reviewed by").
CREATE TABLE content_contact_links (
    content_contact_link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    content_id      INTEGER NOT NULL REFERENCES content(content_id),
    contact_id      INTEGER REFERENCES contacts(contact_id),
    url             TEXT,
    link_type_id    INTEGER REFERENCES content_link_types(content_link_type_id),
    description     TEXT,
    notes           TEXT,                    -- brief summary; web URLs are auto-linked on display
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (contact_id IS NOT NULL OR url IS NOT NULL)
);
CREATE INDEX idx_content_contact_links_tenant ON content_contact_links(tenant_id);
CREATE INDEX idx_content_contact_links_content ON content_contact_links(content_id);
CREATE INDEX idx_content_contact_links_contact ON content_contact_links(contact_id);
CREATE INDEX idx_content_contact_links_type ON content_contact_links(link_type_id);

-- ============================================================================
-- MODULE — DATA EXCHANGE (import / export staging)
-- ============================================================================

CREATE TABLE import_batches (
    batch_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    source_type     TEXT CHECK (source_type IN ('CSV','vCard','JSON')),
    target_module   TEXT NOT NULL,          -- e.g. 'contacts', 'organizations'
    file_name       TEXT,
    imported_at     TEXT NOT NULL DEFAULT (datetime('now')),
    status          TEXT NOT NULL DEFAULT 'Staged' CHECK (status IN ('Staged','Validated','Committed','Rejected')),
    row_count       INTEGER DEFAULT 0,
    error_count     INTEGER DEFAULT 0
);
CREATE INDEX idx_import_batches_tenant ON import_batches(tenant_id);

CREATE TABLE import_staging_rows (
    staging_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    batch_id        INTEGER NOT NULL REFERENCES import_batches(batch_id),
    raw_data        TEXT NOT NULL,          -- JSON blob of the source row
    validation_status TEXT NOT NULL DEFAULT 'Pending' CHECK (validation_status IN ('Pending','Valid','Invalid')),
    validation_errors TEXT,
    committed_entity_id INTEGER             -- nullable, filled in after commit
);
CREATE INDEX idx_import_staging_rows_tenant ON import_staging_rows(tenant_id);
CREATE INDEX idx_import_staging_rows_batch ON import_staging_rows(batch_id);

CREATE TABLE export_jobs (
    export_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    module          TEXT NOT NULL,
    format          TEXT CHECK (format IN ('CSV','JSON','vCard','PDF')),
    filters         TEXT,                   -- JSON
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    file_path       TEXT
);
CREATE INDEX idx_export_jobs_tenant ON export_jobs(tenant_id);

-- ============================================================================
-- SYSTEM MANAGEMENT MODULE
--
-- Table Maintenance has no schema section of its own — it is a generic
-- CRUD blueprint over every tenant-scoped lookup table above (Contact
-- Categories, Titles, Suffixes, Professions, Contexts, Organization Types,
-- Organization Address/Phone Types, Knowledge Domains/Subdomains, Content
-- Types/Subtypes, Content Link Types), plus a separate Geography
-- Maintenance screen for the global regions/countries/states/cities tables
-- (editing those affects every tenant, not just the editor's own — same
-- split TMS used).
-- ============================================================================

CREATE TABLE audit_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER REFERENCES tenants(tenant_id),  -- NULL for pre-login/system-level events (e.g. failed login before the tenant is known, tenant provisioning by a SystemAdmin)
    user_id         INTEGER REFERENCES users(user_id),      -- NULL for failed logins / system events
    ts              TEXT NOT NULL DEFAULT (datetime('now')),
    action          TEXT NOT NULL,          -- Create / Update / Delete / Login / Import / Export / Purge / Archive / ProvisionTenant
    entity_type     TEXT,
    entity_id       INTEGER,
    detail          TEXT
);
CREATE INDEX idx_audit_log_tenant_ts ON audit_log(tenant_id, ts);
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);

-- A log row per CSV file produced by "Archive entries older than 1 year" on
-- the Audit Log page. Whole-database (every tenant's rows plus system-level
-- ones), a SystemAdmin operation, same as `backups` below.
CREATE TABLE audit_log_archives (
    archive_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name       TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    row_count       INTEGER NOT NULL,
    oldest_ts       TEXT,                    -- ts of the oldest row in this archive
    newest_ts       TEXT,                    -- ts of the newest row in this archive (just under the cutoff)
    cutoff_ts       TEXT NOT NULL,            -- the "older than" cutoff used for this run
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_audit_log_archives_created ON audit_log_archives(created_at DESC);

-- A log row per backup file under instance/backups/. Whole-database (every
-- tenant's data lives in the one SQLite file), so this is a SystemAdmin
-- operation, not a per-tenant one. 'Manual' = created from the Backup &
-- Restore page. 'Pre-restore safety' = taken automatically right before a
-- restore overwrites the live database. 'Restore point' is a marker
-- appended to the (now-restored) log recording what the database was just
-- restored from.
CREATE TABLE backups (
    backup_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name       TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    table_count     INTEGER,
    total_rows      INTEGER,
    integrity_ok    INTEGER,                -- 1/0 — PRAGMA integrity_check result captured at backup time
    backup_type     TEXT NOT NULL DEFAULT 'Manual' CHECK (backup_type IN ('Manual','Pre-restore safety','Restore point')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    notes           TEXT
);
CREATE INDEX idx_backups_created ON backups(created_at DESC);
