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
    -- Permanent, auto-generated, numeric billing/account identifier --
    -- deliberately a SEPARATE field from tenant_code above, never
    -- repurposed from it: tenant_code is a human-readable text slug chosen
    -- for internal readability, while account_number must be numeric,
    -- mechanically generated (no human judgment involved) and gap-free in
    -- intent. NULL only transiently, for a row inserted before this column
    -- existed and not yet backfilled (see db.py's
    -- _migration_backfill_tenant_account_numbers) -- every tenant created
    -- through the app (provision_tenant(), seed_first_tenant()) gets one
    -- immediately. Always assigned via db.py's next_account_number(), which
    -- draws from the dedicated tenant_account_number_seq counter below --
    -- NEVER derived from MAX(account_number)+1 or from tenant_id, both of
    -- which would let a deleted tenant's number be handed to someone else.
    -- 10000001 is permanently reserved for the "GSS Platform" reserved
    -- tenant row (see db.py's _migration_create_platform_tenant); real
    -- tenants start at 10000002. Business rule this exists to support (no
    -- delete-tenant feature exists yet, so nothing enforces this today, but
    -- the numbering already assumes it): a tenant with ANY activity can
    -- only ever be suspended, never deleted -- so a number can only ever
    -- become eligible for deletion if the tenant never did anything, and
    -- even then the counter still won't reuse it.
    account_number  INTEGER UNIQUE,
    tenant_name     TEXT NOT NULL,           -- display name, e.g. 'Granite Signal Systems'
    -- True only for the single reserved "GSS Platform" row (account_number
    -- 10000001) -- never a real customer, holds no users, never shown in
    -- Tenant Management's list, and never suspendable/toggleable (see
    -- blueprints/tenants_admin.py's list_tenants()/toggle_status()). A
    -- dedicated flag rather than matching on tenant_code everywhere, so
    -- every check stays correct even if that code is ever renamed.
    is_platform     INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Suspended')),
    dek_wrapped     BLOB NOT NULL,           -- Fernet(system tenant-master-key).encrypt(tenant DEK) — see security/crypto.py + config.get_tenant_master_key()
    data_retention_days INTEGER DEFAULT NULL, -- days from a record's date of entry (created_at) until purge-eligible; NULL = indefinite (never auto-purge). Per-tenant.
    last_purge_at   TEXT,                    -- last time this tenant's purge check actually ran (once/day, checked at login), regardless of whether anything was purged
    -- The tenant's own registered/mailing address -- one single flat address
    -- (not multi-valued, no history), shown on System Management > Account.
    -- Same flat street/city/state/postal_code shape as organizations' Main
    -- Address quick fields, for the same reason: this is a one-off display
    -- field, not something that needs the full Region/Country/Province/
    -- City geography cascade addresses/organization_addresses use.
    address_street  TEXT,
    address_city    TEXT,
    address_state   TEXT,
    address_postal_code TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Dedicated, monotonically-increasing counter behind tenants.account_number
-- (see db.py's next_account_number()). A single row, always id=1. Kept as
-- its own tiny table rather than folded into tenants so it survives and
-- keeps counting regardless of which tenant rows get inserted or (per the
-- business rule above) eventually deleted.
CREATE TABLE tenant_account_number_seq (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    next_value      INTEGER NOT NULL
);
INSERT INTO tenant_account_number_seq (id, next_value) VALUES (1, 10000001);

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
-- MODULE AGENTS — AGENTS LIBRARY, MODELS &amp; BILLING
--
-- A platform-wide catalog of optional AI-powered "agents" (today: the two
-- AI-import features under Data Exchange / Organizations). A tenant does
-- not get an agent automatically -- it shows up locked in their Agents
-- Library screen until a TenantAdmin requests it and a SystemAdmin
-- approves it (see blueprints/agents.py, agents.py's agent_access_required
-- decorator) -- UNLESS the agent is a tenant-scoped "custom agent"
-- (agents_library.tenant_id set), which is auto-approved instead (see
-- blueprints/agents.py's request_access()).
--
-- ai_providers / ai_models / ai_model_rates is the model catalog each
-- agent runs on, with a dated cost-rate history so a profit/loss
-- computation for a past call always uses the rate that was really in
-- force then. agent_pricing_plans is what a tenant is actually charged
-- (flat-monthly-with-included-units-and-overage, or per-transaction);
-- tenant_agents.pricing_plan_id records which plan a tenant is on.
-- tenant_model_credentials holds a tenant's own provider API key,
-- encrypted under that tenant's DEK (security/crypto.py), for a model
-- that requires one -- independent of which pricing plan the tenant is
-- on. agent_usage_log is the append-only actual-usage record billing is
-- computed from: see agent_billing.py for the cost/cap math, and the
-- design rationale in the project doc
-- claude/GSS_Agents_Billing_Architecture_v1.md.
-- ============================================================================

-- GLOBAL (no tenant_id) -- the company behind a model. Anthropic today,
-- room for other providers later.
CREATE TABLE ai_providers (
    provider_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_code   TEXT NOT NULL UNIQUE,    -- e.g. 'ANTHROPIC'
    name            TEXT NOT NULL,           -- e.g. 'Anthropic'
    is_active       INTEGER NOT NULL DEFAULT 1
);

-- GLOBAL -- the catalog of models an agent can run on.
CREATE TABLE ai_models (
    model_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id     INTEGER NOT NULL REFERENCES ai_providers(provider_id),
    model_code      TEXT NOT NULL UNIQUE,    -- e.g. 'claude-sonnet-5' -- matches CLAUDE_IMPORT_MODEL / the model string sent to the provider's API
    display_name    TEXT NOT NULL,           -- e.g. 'Claude Sonnet 5'
    requires_tenant_api_key INTEGER NOT NULL DEFAULT 0,  -- 0: runs on the platform's own shared ANTHROPIC_API_KEY; 1: a tenant must supply their own key (tenant_model_credentials) to use this model
    is_active       INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER DEFAULT 0
);
CREATE INDEX idx_ai_models_provider ON ai_models(provider_id);

-- GLOBAL -- dated cost history for a model. The rate in force at a given
-- moment is the row with the latest effective_from <= that moment, for
-- that model -- see agent_billing.py compute_cost(). A price change never
-- rewrites a past agent_usage_log row's actual_cost, because that cost
-- was computed and stored at the time, not recalculated later.
CREATE TABLE ai_model_rates (
    rate_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id        INTEGER NOT NULL REFERENCES ai_models(model_id),
    effective_from  TEXT NOT NULL,           -- date (or datetime) this rate took effect
    cost_per_1k_input_tokens  REAL NOT NULL,
    cost_per_1k_output_tokens REAL NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'USD'
);
CREATE INDEX idx_ai_model_rates_model_effective ON ai_model_rates(model_id, effective_from);

-- GLOBAL (no tenant_id) -- the catalog itself is platform-wide, same as
-- regions/countries below; what's tenant-specific is whether a given
-- tenant has been granted a given agent (tenant_agents, below). The one
-- exception is a CUSTOM agent (tenant_id set below): still one row here,
-- but visible/usable by only that one tenant.
CREATE TABLE agents_library (
    agent_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER REFERENCES tenants(tenant_id),  -- NULL: platform-wide agent, visible to every tenant (today's two agents). Set: a CUSTOM agent built for this one tenant only -- visible solely on their own Agents Library, and auto-approved on request rather than queued for SystemAdmin review.
    agent_code      TEXT NOT NULL UNIQUE,    -- stable internal key, e.g. 'business_card_import' -- referenced from code, never shown to a user
    name            TEXT NOT NULL,           -- e.g. 'AI Business Card Import'
    description     TEXT,
    category        TEXT,                    -- e.g. 'AI Import' -- free text, for grouping the library screen later
    default_model_id INTEGER REFERENCES ai_models(model_id),  -- which ai_models row this agent runs on by default
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,  -- the platform can retire an agent from the catalog without deleting usage history
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_agents_library_tenant ON agents_library(tenant_id);

-- What a tenant is charged to use an agent. One agent can offer more than
-- one plan (e.g. a Basic and a Pro tier); a tenant's chosen plan is
-- recorded on tenant_agents.pricing_plan_id. Two fee shapes:
--   'flat_monthly'    -- flat_fee_amount per month, covering up to
--                         included_units_per_cycle uses; overage_unit_fee
--                         per extra use beyond that. GSS's policy (see
--                         agent_billing.py) is to NEVER block a run once
--                         the cap is crossed -- overage is billed, not
--                         gated -- with a warning shown from 90% of the
--                         cap onward.
--   'per_transaction' -- no flat fee, per_transaction_fee charged per use.
CREATE TABLE agent_pricing_plans (
    plan_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        INTEGER NOT NULL REFERENCES agents_library(agent_id),
    plan_code       TEXT NOT NULL,           -- unique per agent, e.g. 'standard_monthly'
    plan_name       TEXT NOT NULL,           -- e.g. 'Standard Monthly'
    pricing_model   TEXT NOT NULL CHECK (pricing_model IN ('flat_monthly','per_transaction')),
    flat_fee_amount REAL,                    -- flat_monthly only
    included_units_per_cycle INTEGER,        -- flat_monthly only
    overage_unit_fee REAL,                   -- flat_monthly only -- price per use beyond included_units_per_cycle
    per_transaction_fee REAL,                -- per_transaction only
    required_model_id INTEGER REFERENCES ai_models(model_id),  -- if set and that model requires_tenant_api_key, a tenant needs a tenant_model_credentials row before this plan will work for them
    currency        TEXT NOT NULL DEFAULT 'USD',
    effective_from  TEXT NOT NULL DEFAULT (date('now')),
    effective_to    TEXT,                    -- NULL: current/open-ended
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (agent_id, plan_code)
);
CREATE INDEX idx_agent_pricing_plans_agent ON agent_pricing_plans(agent_id);

-- One row per (tenant, agent) a tenant has ever requested. No row at all
-- means "never requested" -- the library screen shows every catalog agent
-- with whichever of these four states applies, defaulting to "not
-- requested" when there's no row yet. Once Approved, pricing_plan_id /
-- subscribed_at make this row double as the tenant's subscription record
-- for that agent -- subscribed_at is also the monthly anchor date the
-- usage cycle (and the 90% cap warning) counts from.
CREATE TABLE tenant_agents (
    tenant_agent_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    agent_id        INTEGER NOT NULL REFERENCES agents_library(agent_id),
    status          TEXT NOT NULL DEFAULT 'Requested' CHECK (status IN ('Requested','Approved','Denied','Revoked')),
    requested_by_user_id INTEGER REFERENCES users(user_id),
    requested_at    TEXT NOT NULL DEFAULT (datetime('now')),
    decided_by_user_id INTEGER REFERENCES users(user_id),  -- the SystemAdmin who approved/denied/revoked -- NULL while still Requested
    decided_at      TEXT,
    notes           TEXT,
    pricing_plan_id INTEGER REFERENCES agent_pricing_plans(plan_id),  -- which plan this tenant is billed under; NULL until one is chosen
    subscribed_at   TEXT,                    -- when pricing_plan_id was (last) set
    UNIQUE (tenant_id, agent_id)
);
CREATE INDEX idx_tenant_agents_tenant ON tenant_agents(tenant_id);
CREATE INDEX idx_tenant_agents_agent ON tenant_agents(agent_id);

-- A tenant's own provider API key/credential, for an agent/model that
-- requires one (ai_models.requires_tenant_api_key). Scoped to PROVIDER,
-- not model -- one Anthropic key covers every Anthropic model, same as
-- the platform's own shared ANTHROPIC_API_KEY does today. The key itself
-- is encrypted under the tenant's own DEK (security/crypto.py), the same
-- mechanism GSS already uses for every other encrypted field, so it's
-- never readable outside a logged-in session for that tenant.
--
-- Only one credential may be ACTIVE per (tenant, provider) at a time --
-- enforced by the partial unique index below, not a table-level UNIQUE --
-- so a tenant can hold an inactive spare (a rotated-out key kept for
-- reference, or a not-yet-activated replacement) without violating it;
-- supporting true overlapping key rotation later means only dropping that
-- index, not a schema change.
CREATE TABLE tenant_model_credentials (
    credential_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    provider_id     INTEGER NOT NULL REFERENCES ai_providers(provider_id),
    api_key_wrapped BLOB NOT NULL,           -- Fernet-encrypted under this tenant's DEK -- see security/crypto.py encrypt_value/decrypt_value
    label           TEXT,                    -- tenant's own nickname, e.g. 'Production key'
    added_by_user_id INTEGER REFERENCES users(user_id),
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    last_used_at    TEXT,
    notes           TEXT
);
CREATE INDEX idx_tenant_model_credentials_tenant ON tenant_model_credentials(tenant_id);
CREATE UNIQUE INDEX idx_tenant_model_credentials_active ON tenant_model_credentials(tenant_id, provider_id) WHERE is_active = 1;

-- Append-only usage record -- one row per successful agent invocation
-- (e.g. one business-card extraction, one ad photo extracted). "units"
-- defaults to 1 (one call = one unit) and is what counts against a
-- tenant's plan cap / per-transaction fee. tokens_input/tokens_output/
-- actual_cost/model_id/credential_id carry the real cost numbers a
-- profit/loss report needs -- see agent_billing.py record_usage() and
-- compute_cost().
CREATE TABLE agent_usage_log (
    usage_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    agent_id        INTEGER NOT NULL REFERENCES agents_library(agent_id),
    user_id         INTEGER REFERENCES users(user_id),
    used_at         TEXT NOT NULL DEFAULT (datetime('now')),
    units           INTEGER NOT NULL DEFAULT 1,
    detail          TEXT,
    model_id        INTEGER REFERENCES ai_models(model_id),        -- which model actually served this call; NULL for a call made before this column existed
    credential_id   INTEGER REFERENCES tenant_model_credentials(credential_id),  -- which of the tenant's own keys was used; NULL means the platform's shared key
    tokens_input    INTEGER,                 -- from the provider's response
    tokens_output   INTEGER,
    actual_cost     REAL                     -- tokens x the ai_model_rates row in force at used_at
);
CREATE INDEX idx_agent_usage_log_tenant_agent ON agent_usage_log(tenant_id, agent_id);
CREATE INDEX idx_agent_usage_log_used_at ON agent_usage_log(used_at);

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

-- Lookup for organizations.size_category_id (below) — a coarse headcount
-- bucket (Small/Medium-Small/Medium/Large). min_employees/max_employees
-- (max NULL = no upper bound) drive the form's auto-suggest from a typed
-- Number of Employees value; the category itself can still be picked or
-- overridden by hand independent of that number.
CREATE TABLE organization_size_categories (
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
);
CREATE INDEX idx_organization_size_categories_tenant ON organization_size_categories(tenant_id);

-- Lookup for organizations.organization_domain_id (below) — the industry/
-- sector an organization operates in (e.g. "Healthcare & Hospitals").
CREATE TABLE organization_domains (
    organization_domain_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_organization_domains_tenant ON organization_domains(tenant_id);

-- One level of nesting under organization_domains (e.g. domain "Healthcare
-- & Hospitals" -> sub-domains "General Acute Care Hospitals", "Telemedicine
-- Platforms"). Added via Table Maintenance, same nesting pattern as
-- knowledge_subdomains/content_subtypes below.
CREATE TABLE organization_subdomains (
    organization_subdomain_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    organization_domain_id INTEGER NOT NULL REFERENCES organization_domains(organization_domain_id),
    code            TEXT,
    label           TEXT NOT NULL,
    description     TEXT,
    sort_order      INTEGER DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (tenant_id, code)
);
CREATE INDEX idx_organization_subdomains_tenant ON organization_subdomains(tenant_id);
CREATE INDEX idx_organization_subdomains_domain ON organization_subdomains(organization_domain_id);

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
-- organization_phones tables (own type lookups above) for organizations that
-- need more than one of each (e.g. a Mailing Address and a Physical Address,
-- or several phone lines by type), each entered on its own card on the
-- organization's page after the record exists.
--
-- street/city/state/postal_code/phone/fax/email are a separate "Main
-- Address / Main Phone / Main Fax / Main Email" quick-contact set kept
-- directly on `organizations` itself — plain optional text, not linked to
-- any address-type lookup, geography table (no country/state/city_id —
-- that linking is what organization_addresses is for), or uploaded file,
-- and not required: most Organizations here are prospects/leads and many
-- never get a full structured address on file. They're set on the main
-- Organization form as separate Street/City/State/Zip fields; the detailed
-- multi-valued cards above are for anything beyond that.
--
-- full_address is the older single-blob version of the same idea
-- (originally PIMS's flat shape). The Organization form itself no longer
-- reads or writes it — street/city/state/postal_code superseded it there —
-- but it's left in place because Contacts' quick "add organization" form
-- and the Organizations CSV importer (see blueprints/contacts.py and
-- data_exchange.py) still write a single combined address string into it;
-- the Organization view page falls back to displaying it when the
-- structured fields are still blank, so nothing entered through those
-- other two paths becomes invisible.
-- ============================================================================

CREATE TABLE organizations (
    organization_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    organization_name TEXT NOT NULL,
    full_address    TEXT,                   -- legacy combined "Main Address" blob — see module note above
    street          TEXT,                   -- "Main Address" street line — see module note above
    city            TEXT,                   -- "Main Address" city
    state           TEXT,                   -- "Main Address" state/province, free text
    postal_code     TEXT,                   -- "Main Address" zip/postal code
    phone           TEXT,                   -- "Main Phone" — see module note above
    fax             TEXT,                   -- "Main Fax" — see module note above
    email           TEXT,                   -- "Main Email" — see module note above
    website         TEXT,
    organization_type_id INTEGER REFERENCES organization_types(organization_type_id),
    number_of_employees INTEGER,             -- actual headcount, entered directly
    size_category_id INTEGER REFERENCES organization_size_categories(size_category_id),
    organization_domain_id INTEGER REFERENCES organization_domains(organization_domain_id),
    organization_subdomain_id INTEGER REFERENCES organization_subdomains(organization_subdomain_id),
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

-- Ad/Listing import -- mirrors the Real Estate Agent reference app's
-- AI-powered flyer-to-listing import (ai_import.py / admin.py), generalized
-- from real-estate flyers to any advertisement or marketing material for an
-- Organization: a magazine ad, a "Help Wanted" clipping, a social-media
-- post screenshot, an online ad. One Organization can have any number of
-- these Ad Listings, each with its own photo(s) kept as the permanent
-- record of what the ad actually said (see organization_ad_photos below
-- and ad_import.py's module docstring) -- "Maintain the Original ads in a
-- Listing" per the feature request.
CREATE TABLE organization_ad_listings (
    ad_listing_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),
    headline        TEXT NOT NULL,           -- the ad's title/headline -- this feature's durable match key for update-in-place, the way a real-estate listing matches on address
    ad_type         TEXT NOT NULL DEFAULT 'Print' CHECK (ad_type IN ('Print','Online','Social Media','Classified','Direct Mail','Broadcast','Other')),
    publication     TEXT,                    -- magazine/website/newspaper/platform name the ad ran in
    date_published  TEXT,                    -- ISO date YYYY-MM-DD, only when actually printed/shown on the ad
    description     TEXT,                    -- body/content of the ad, as read
    offer_details   TEXT,                    -- promotional offer / call to action, free text
    price           REAL,                    -- a price or offer amount printed on the ad, if any
    price_label     TEXT,                    -- what that price means, e.g. "Starting at", "Sale Price", "/month"
    contact_name    TEXT,                    -- contact info AS PRINTED ON THE AD -- kept here, not synced onto the Organization's own emails/phones (see ad_import.py)
    contact_phone   TEXT,
    contact_email   TEXT,
    status          TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Expired','Archived')),
    source          TEXT,                    -- 'Magazine','Newspaper','Online','Social Media','Manual Entry'
    source_notes    TEXT,                    -- AI extraction notes: ambiguity, what wasn't printed, etc.
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_organization_ad_listings_tenant ON organization_ad_listings(tenant_id);
CREATE INDEX idx_organization_ad_listings_org ON organization_ad_listings(organization_id);

-- Mirrors listings.price_history in the reference app: the OLD price is
-- snapshotted here right before update-in-place (re-importing a later
-- version of the same ad) would otherwise silently overwrite it.
CREATE TABLE organization_ad_price_history (
    ad_price_history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    ad_listing_id   INTEGER NOT NULL REFERENCES organization_ad_listings(ad_listing_id),
    price           REAL NOT NULL,
    price_label     TEXT,
    effective_date  TEXT,
    recorded_at     TEXT NOT NULL DEFAULT (datetime('now')),
    note            TEXT
);
CREATE INDEX idx_organization_ad_price_history_listing ON organization_ad_price_history(ad_listing_id);

-- Free-form, dated notes about an ad listing -- mirrors listing_notes.
CREATE TABLE organization_ad_notes (
    ad_note_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    ad_listing_id   INTEGER NOT NULL REFERENCES organization_ad_listings(ad_listing_id),
    note_text       TEXT NOT NULL,
    note_date       TEXT NOT NULL DEFAULT (date('now')),
    source          TEXT,                    -- 'Ad Import', 'Batch Import', 'Manual'
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_organization_ad_notes_listing ON organization_ad_notes(ad_listing_id);

-- The original ad image(s). Stored as files under Config.AD_PHOTOS_DIR
-- (GSS's file-on-disk convention -- see contacts.business_card_front_path/
-- back_path -- rather than the reference app's in-database BLOB), never
-- normalized/downscaled, so the literal source material is always there to
-- look back at.
CREATE TABLE organization_ad_photos (
    ad_photo_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    ad_listing_id   INTEGER NOT NULL REFERENCES organization_ad_listings(ad_listing_id),
    image_path      TEXT NOT NULL,           -- filename under Config.AD_PHOTOS_DIR
    mime_type       TEXT NOT NULL DEFAULT 'image/jpeg',
    original_filename TEXT,
    caption         TEXT,
    source          TEXT,                    -- 'Ad Import', 'Batch Import', 'Manual Upload'
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_organization_ad_photos_listing ON organization_ad_photos(ad_listing_id);

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
    business_card_front_path TEXT,          -- uploaded photo/scan of the business card's front face
    business_card_back_path  TEXT,          -- optional back face; the view page flips between them in place when both are on file
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

-- ============================================================================
-- TENANT ISOLATION — cross-tenant foreign-key guards
--
-- PRAGMA foreign_keys = ON already guarantees a referenced row EXISTS, but
-- not that it belongs to the same tenant as the row pointing at it. Every
-- route that saves one of these foreign keys already renders its picker
-- from a tenant-scoped query, so this should never fire in normal use — it
-- exists as a hard backstop against a form-submitted id for another
-- tenant's row (whether from a bug, a hand-crafted request, or a future
-- route that forgets the WHERE tenant_id = ? clause). A URL-path-segment id
-- (e.g. /organizations/<org_id>) is a different, already-covered case —
-- every route that takes one filters its lookup by tenant_id itself; these
-- triggers cover the id-picked-from-a-dropdown case instead.
--
-- Covers every relationship Table Maintenance manages (see
-- blueprints/table_maintenance.py TABLES) plus the highest-value
-- entity-level pickers (a Contact's Organization/Assistant, a Content
-- item's linked Contact). Not exhaustive of every foreign key in this
-- schema — organization_id/content_id-style columns that are always taken
-- from a URL path segment are intentionally left alone, since those are
-- already tenant-checked at the route level.
-- ============================================================================

CREATE TRIGGER trg_tenant_fk_contacts_contact_category_id_ins
BEFORE INSERT ON contacts
WHEN NEW.contact_category_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.contact_category_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contact_categories
        WHERE contact_category_id = NEW.contact_category_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_contact_category_id_upd
BEFORE UPDATE ON contacts
WHEN NEW.contact_category_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.contact_category_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contact_categories
        WHERE contact_category_id = NEW.contact_category_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_title_id_ins
BEFORE INSERT ON contacts
WHEN NEW.title_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.title_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contact_titles
        WHERE contact_title_id = NEW.title_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_title_id_upd
BEFORE UPDATE ON contacts
WHEN NEW.title_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.title_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contact_titles
        WHERE contact_title_id = NEW.title_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_suffix_id_ins
BEFORE INSERT ON contacts
WHEN NEW.suffix_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.suffix_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contact_suffixes
        WHERE contact_suffix_id = NEW.suffix_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_suffix_id_upd
BEFORE UPDATE ON contacts
WHEN NEW.suffix_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.suffix_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contact_suffixes
        WHERE contact_suffix_id = NEW.suffix_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_profession_id_ins
BEFORE INSERT ON contacts
WHEN NEW.profession_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.profession_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM professions
        WHERE profession_id = NEW.profession_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_profession_id_upd
BEFORE UPDATE ON contacts
WHEN NEW.profession_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.profession_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM professions
        WHERE profession_id = NEW.profession_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_context_id_ins
BEFORE INSERT ON contacts
WHEN NEW.context_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.context_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contact_contexts
        WHERE contact_context_id = NEW.context_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_context_id_upd
BEFORE UPDATE ON contacts
WHEN NEW.context_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.context_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contact_contexts
        WHERE contact_context_id = NEW.context_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organizations_organization_type_id_ins
BEFORE INSERT ON organizations
WHEN NEW.organization_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organizations.organization_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_types
        WHERE organization_type_id = NEW.organization_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organizations_organization_type_id_upd
BEFORE UPDATE ON organizations
WHEN NEW.organization_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organizations.organization_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_types
        WHERE organization_type_id = NEW.organization_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organization_addresses_address_type_id_ins
BEFORE INSERT ON organization_addresses
WHEN NEW.address_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organization_addresses.address_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_address_types
        WHERE address_type_id = NEW.address_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organization_addresses_address_type_id_upd
BEFORE UPDATE ON organization_addresses
WHEN NEW.address_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organization_addresses.address_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_address_types
        WHERE address_type_id = NEW.address_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organization_phones_phone_type_id_ins
BEFORE INSERT ON organization_phones
WHEN NEW.phone_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organization_phones.phone_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_phone_types
        WHERE phone_type_id = NEW.phone_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organization_phones_phone_type_id_upd
BEFORE UPDATE ON organization_phones
WHEN NEW.phone_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organization_phones.phone_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_phone_types
        WHERE phone_type_id = NEW.phone_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_knowledge_domains_knowledge_domain_id_ins
BEFORE INSERT ON content_knowledge_domains
WHEN NEW.knowledge_domain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content_knowledge_domains.knowledge_domain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM knowledge_domains
        WHERE knowledge_domain_id = NEW.knowledge_domain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_knowledge_domains_knowledge_domain_id_upd
BEFORE UPDATE ON content_knowledge_domains
WHEN NEW.knowledge_domain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content_knowledge_domains.knowledge_domain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM knowledge_domains
        WHERE knowledge_domain_id = NEW.knowledge_domain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_content_type_id_ins
BEFORE INSERT ON content
WHEN NEW.content_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content.content_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM content_types
        WHERE content_type_id = NEW.content_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_content_type_id_upd
BEFORE UPDATE ON content
WHEN NEW.content_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content.content_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM content_types
        WHERE content_type_id = NEW.content_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_contact_links_link_type_id_ins
BEFORE INSERT ON content_contact_links
WHEN NEW.link_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content_contact_links.link_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM content_link_types
        WHERE content_link_type_id = NEW.link_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_contact_links_link_type_id_upd
BEFORE UPDATE ON content_contact_links
WHEN NEW.link_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content_contact_links.link_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM content_link_types
        WHERE content_link_type_id = NEW.link_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organizations_size_category_id_ins
BEFORE INSERT ON organizations
WHEN NEW.size_category_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organizations.size_category_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_size_categories
        WHERE size_category_id = NEW.size_category_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organizations_size_category_id_upd
BEFORE UPDATE ON organizations
WHEN NEW.size_category_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organizations.size_category_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_size_categories
        WHERE size_category_id = NEW.size_category_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organizations_organization_domain_id_ins
BEFORE INSERT ON organizations
WHEN NEW.organization_domain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organizations.organization_domain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_domains
        WHERE organization_domain_id = NEW.organization_domain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organizations_organization_domain_id_upd
BEFORE UPDATE ON organizations
WHEN NEW.organization_domain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organizations.organization_domain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_domains
        WHERE organization_domain_id = NEW.organization_domain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organizations_organization_subdomain_id_ins
BEFORE INSERT ON organizations
WHEN NEW.organization_subdomain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organizations.organization_subdomain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_subdomains
        WHERE organization_subdomain_id = NEW.organization_subdomain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organizations_organization_subdomain_id_upd
BEFORE UPDATE ON organizations
WHEN NEW.organization_subdomain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organizations.organization_subdomain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_subdomains
        WHERE organization_subdomain_id = NEW.organization_subdomain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_knowledge_subdomains_knowledge_domain_id_ins
BEFORE INSERT ON knowledge_subdomains
WHEN NEW.knowledge_domain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'knowledge_subdomains.knowledge_domain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM knowledge_domains
        WHERE knowledge_domain_id = NEW.knowledge_domain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_knowledge_subdomains_knowledge_domain_id_upd
BEFORE UPDATE ON knowledge_subdomains
WHEN NEW.knowledge_domain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'knowledge_subdomains.knowledge_domain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM knowledge_domains
        WHERE knowledge_domain_id = NEW.knowledge_domain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_subtypes_content_type_id_ins
BEFORE INSERT ON content_subtypes
WHEN NEW.content_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content_subtypes.content_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM content_types
        WHERE content_type_id = NEW.content_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_subtypes_content_type_id_upd
BEFORE UPDATE ON content_subtypes
WHEN NEW.content_type_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content_subtypes.content_type_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM content_types
        WHERE content_type_id = NEW.content_type_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organization_subdomains_organization_domain_id_ins
BEFORE INSERT ON organization_subdomains
WHEN NEW.organization_domain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organization_subdomains.organization_domain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_domains
        WHERE organization_domain_id = NEW.organization_domain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_organization_subdomains_organization_domain_id_upd
BEFORE UPDATE ON organization_subdomains
WHEN NEW.organization_domain_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'organization_subdomains.organization_domain_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organization_domains
        WHERE organization_domain_id = NEW.organization_domain_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_current_organization_id_ins
BEFORE INSERT ON contacts
WHEN NEW.current_organization_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.current_organization_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organizations
        WHERE organization_id = NEW.current_organization_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_current_organization_id_upd
BEFORE UPDATE ON contacts
WHEN NEW.current_organization_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.current_organization_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organizations
        WHERE organization_id = NEW.current_organization_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_assistant_contact_id_ins
BEFORE INSERT ON contacts
WHEN NEW.assistant_contact_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.assistant_contact_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contacts
        WHERE contact_id = NEW.assistant_contact_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_contacts_assistant_contact_id_upd
BEFORE UPDATE ON contacts
WHEN NEW.assistant_contact_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'contacts.assistant_contact_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contacts
        WHERE contact_id = NEW.assistant_contact_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_contact_links_contact_id_ins
BEFORE INSERT ON content_contact_links
WHEN NEW.contact_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content_contact_links.contact_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contacts
        WHERE contact_id = NEW.contact_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_content_contact_links_contact_id_upd
BEFORE UPDATE ON content_contact_links
WHEN NEW.contact_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'content_contact_links.contact_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contacts
        WHERE contact_id = NEW.contact_id AND tenant_id = NEW.tenant_id
    );
END;

-- =============================================================================
-- MODULE — CLIENT ACQUISITION (sales pipeline / CRM)
-- =============================================================================
-- An Opportunity tracks one prospective client's journey toward becoming a
-- client, moving through a tenant's own Pipeline Template (a named sequence
-- of stages, each with a typical time window, a checklist of required
-- actions, and a pre-defined outreach cadence). Opportunities link to
-- EXISTING organizations/contacts rows -- there is deliberately no separate
-- "clients" table (see the GSS_Data_Model_Decisions_v1.md project doc's
-- Client Acquisition addendum for the full set of decisions this module
-- implements).
--
-- Pipeline Templates are seeded once onto the reserved GSS_PLATFORM tenant
-- (tenant_code = 'GSS_PLATFORM', see this file's tenants.is_platform comment
-- and db.py's _migration_create_platform_tenant) and cloned into every
-- tenant at provisioning time (tenant_provisioning.py's provision_tenant()),
-- the same as every other per-tenant lookup table -- once cloned, a tenant
-- is free to edit its own copy without affecting the platform master or any
-- other tenant's copy.
--
-- Controlled vocabularies below (channel, direction, outcome, lost_reason,
-- nurture_reason, contact_role, task source) are FIXED via CHECK
-- constraints -- the same pattern already used for contact_phones.
-- phone_type above -- NOT tenant-editable Table Maintenance lookups, unlike
-- e.g. Contact Categories/Organization Types. This keeps them comparable
-- across every tenant for reporting, and was a deliberate choice rather
-- than an oversight.
--
-- "Customer Service" (customer complaints/tickets/delivery) is intentionally
-- a separate, not-yet-built module -- see blueprints/customer_service.py's
-- placeholder page. Nothing here assumes it exists yet.

CREATE TABLE pipeline_templates (
    pipeline_template_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    template_name   TEXT NOT NULL,
    win_criteria_prompt TEXT,               -- freeform: what "won" looks like for this template
    disqualify_after_days INTEGER,          -- default staleness threshold; an Opportunity can override its own
    is_active       INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(tenant_id, template_name)
);
CREATE INDEX idx_pipeline_templates_tenant ON pipeline_templates(tenant_id);

CREATE TABLE pipeline_template_stages (
    stage_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    pipeline_template_id INTEGER NOT NULL REFERENCES pipeline_templates(pipeline_template_id),
    stage_number    INTEGER NOT NULL,
    stage_name      TEXT NOT NULL,
    typical_window_days INTEGER,            -- expected days in this stage; drives the "aging" risk flag
    probability_percent INTEGER NOT NULL DEFAULT 0 CHECK (probability_percent BETWEEN 0 AND 100),
    UNIQUE(pipeline_template_id, stage_number)
);
CREATE INDEX idx_pipeline_template_stages_tenant ON pipeline_template_stages(tenant_id);
CREATE INDEX idx_pipeline_template_stages_template ON pipeline_template_stages(pipeline_template_id);

CREATE TABLE pipeline_template_checklist_items (
    checklist_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    pipeline_template_id INTEGER NOT NULL REFERENCES pipeline_templates(pipeline_template_id),
    stage_number    INTEGER NOT NULL,
    item_label      TEXT NOT NULL,
    is_required     INTEGER NOT NULL DEFAULT 1,   -- required items gate stage advancement; see opportunity_stage_checklist_progress
    sort_order      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_pipeline_template_checklist_tenant ON pipeline_template_checklist_items(tenant_id);
CREATE INDEX idx_pipeline_template_checklist_template ON pipeline_template_checklist_items(pipeline_template_id);

CREATE TABLE pipeline_template_cadence_steps (
    cadence_step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    pipeline_template_id INTEGER NOT NULL REFERENCES pipeline_templates(pipeline_template_id),
    stage_number    INTEGER NOT NULL,
    day_offset      INTEGER NOT NULL DEFAULT 0,   -- days after stage entry this task auto-generates on
    action_label    TEXT NOT NULL,
    channel         TEXT CHECK (channel IN ('Call','Email','LinkedIn','Text','In-Person','Mail','Video','Note')),
    sort_order      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_pipeline_template_cadence_tenant ON pipeline_template_cadence_steps(tenant_id);
CREATE INDEX idx_pipeline_template_cadence_template ON pipeline_template_cadence_steps(pipeline_template_id);

CREATE TABLE opportunities (
    opportunity_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    organization_id INTEGER NOT NULL REFERENCES organizations(organization_id),
    pipeline_template_id INTEGER NOT NULL REFERENCES pipeline_templates(pipeline_template_id),
    opportunity_name TEXT NOT NULL,
    assigned_user_id INTEGER REFERENCES users(user_id),   -- owning rep; nullable (unassigned)
    status          TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Nurture','Lost','Closed')),
    current_stage_number INTEGER NOT NULL DEFAULT 1,
    stage_entered_date TEXT NOT NULL DEFAULT (datetime('now')),
    opportunity_value REAL,
    probability_percent INTEGER NOT NULL DEFAULT 0 CHECK (probability_percent BETWEEN 0 AND 100),
    lead_source     TEXT,                    -- hybrid structured/free-text on purpose -- deliberately no CHECK
    lead_source_detail TEXT,
    disqualify_after_days INTEGER,           -- overrides the template's own default when set
    next_action     TEXT,
    next_action_date TEXT,
    nurture_reason  TEXT CHECK (nurture_reason IN ('Timing','Budget Cycle','Internal Change','Rebrand','Hiring Freeze','Other')),
    nurture_revisit_date TEXT,
    lost_reason     TEXT CHECK (lost_reason IN ('Price','Competitor','Timing','No Budget','No Authority','No Need','Unresponsive','Out of Scope')),
    lost_date       TEXT,
    closed_date     TEXT,
    closed_won      INTEGER,                 -- 1 = won/became a client, 0 = closed without winning; NULL until closed
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
    -- No is_deleted -- Nurture/Lost already give this module its "never
    -- delete, only move to a side-state" behavior.
);
CREATE INDEX idx_opportunities_tenant ON opportunities(tenant_id);
CREATE INDEX idx_opportunities_organization ON opportunities(organization_id);
CREATE INDEX idx_opportunities_template ON opportunities(pipeline_template_id);
CREATE INDEX idx_opportunities_assigned_user ON opportunities(assigned_user_id);
CREATE INDEX idx_opportunities_status ON opportunities(status);

CREATE TABLE opportunity_contacts (
    opportunity_contact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
    contact_id      INTEGER NOT NULL REFERENCES contacts(contact_id),
    contact_role    TEXT CHECK (contact_role IN ('Economic Buyer','Champion','Influencer','Blocker','Decision Maker','End User')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(opportunity_id, contact_id)
);
CREATE INDEX idx_opportunity_contacts_tenant ON opportunity_contacts(tenant_id);
CREATE INDEX idx_opportunity_contacts_opportunity ON opportunity_contacts(opportunity_id);
CREATE INDEX idx_opportunity_contacts_contact ON opportunity_contacts(contact_id);

-- Snapshot, not a live join against pipeline_template_checklist_items --
-- copied in at stage-entry time so a later edit to the template doesn't
-- retroactively alter an Opportunity's own history (same reasoning as the
-- CSV-import staging tables' snapshot-not-live-join pattern).
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
);
CREATE INDEX idx_opp_checklist_progress_tenant ON opportunity_stage_checklist_progress(tenant_id);
CREATE INDEX idx_opp_checklist_progress_opportunity ON opportunity_stage_checklist_progress(opportunity_id);

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
    is_manual_override INTEGER NOT NULL DEFAULT 0,   -- advanced/reverted without the checklist being fully complete
    reason          TEXT,                            -- required by the app when is_manual_override=1 or moving to Lost
    changed_by_user_id INTEGER REFERENCES users(user_id),
    changed_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_opp_stage_history_tenant ON opportunity_stage_history(tenant_id);
CREATE INDEX idx_opp_stage_history_opportunity ON opportunity_stage_history(opportunity_id);

CREATE TABLE interactions (
    interaction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       INTEGER NOT NULL REFERENCES tenants(tenant_id),
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(opportunity_id),
    contact_id      INTEGER REFERENCES contacts(contact_id),   -- nullable: e.g. a general voicemail/note not tied to one person
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
);
CREATE INDEX idx_interactions_tenant ON interactions(tenant_id);
CREATE INDEX idx_interactions_opportunity ON interactions(opportunity_id);
CREATE INDEX idx_interactions_contact ON interactions(contact_id);

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
);
CREATE INDEX idx_tasks_tenant ON tasks(tenant_id);
CREATE INDEX idx_tasks_opportunity ON tasks(opportunity_id);
CREATE INDEX idx_tasks_assigned_user ON tasks(assigned_user_id);
CREATE INDEX idx_tasks_due_date ON tasks(due_date);

-- Cross-tenant guard triggers for this module's own "picker" foreign keys
-- (fields populated from a <select> in a form, where a tampered request
-- could otherwise reference another tenant's row) -- same rationale as the
-- TENANT ISOLATION triggers above, kept as their own fresh set (rather than
-- appended to TENANT_FK_CHECKS in db.py) because that list's migration
-- already shipped and past migrations are never edited once applied; see
-- db.py's _migration_client_acquisition_module for this module's own
-- migration-path equivalent of these same triggers.

CREATE TRIGGER trg_tenant_fk_opportunities_organization_id_ins
BEFORE INSERT ON opportunities
WHEN NEW.organization_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'opportunities.organization_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organizations
        WHERE organization_id = NEW.organization_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_opportunities_organization_id_upd
BEFORE UPDATE ON opportunities
WHEN NEW.organization_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'opportunities.organization_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM organizations
        WHERE organization_id = NEW.organization_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_opportunities_pipeline_template_id_ins
BEFORE INSERT ON opportunities
WHEN NEW.pipeline_template_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'opportunities.pipeline_template_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM pipeline_templates
        WHERE pipeline_template_id = NEW.pipeline_template_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_opportunities_pipeline_template_id_upd
BEFORE UPDATE ON opportunities
WHEN NEW.pipeline_template_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'opportunities.pipeline_template_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM pipeline_templates
        WHERE pipeline_template_id = NEW.pipeline_template_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_opportunities_assigned_user_id_ins
BEFORE INSERT ON opportunities
WHEN NEW.assigned_user_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'opportunities.assigned_user_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM users
        WHERE user_id = NEW.assigned_user_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_opportunities_assigned_user_id_upd
BEFORE UPDATE ON opportunities
WHEN NEW.assigned_user_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'opportunities.assigned_user_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM users
        WHERE user_id = NEW.assigned_user_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_opportunity_contacts_contact_id_ins
BEFORE INSERT ON opportunity_contacts
WHEN NEW.contact_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'opportunity_contacts.contact_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contacts
        WHERE contact_id = NEW.contact_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_opportunity_contacts_contact_id_upd
BEFORE UPDATE ON opportunity_contacts
WHEN NEW.contact_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'opportunity_contacts.contact_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contacts
        WHERE contact_id = NEW.contact_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_interactions_contact_id_ins
BEFORE INSERT ON interactions
WHEN NEW.contact_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'interactions.contact_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contacts
        WHERE contact_id = NEW.contact_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_interactions_contact_id_upd
BEFORE UPDATE ON interactions
WHEN NEW.contact_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'interactions.contact_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM contacts
        WHERE contact_id = NEW.contact_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_tasks_assigned_user_id_ins
BEFORE INSERT ON tasks
WHEN NEW.assigned_user_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'tasks.assigned_user_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM users
        WHERE user_id = NEW.assigned_user_id AND tenant_id = NEW.tenant_id
    );
END;

CREATE TRIGGER trg_tenant_fk_tasks_assigned_user_id_upd
BEFORE UPDATE ON tasks
WHEN NEW.assigned_user_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'tasks.assigned_user_id: cross-tenant reference not allowed')
    WHERE NOT EXISTS (
        SELECT 1 FROM users
        WHERE user_id = NEW.assigned_user_id AND tenant_id = NEW.tenant_id
    );
END;
