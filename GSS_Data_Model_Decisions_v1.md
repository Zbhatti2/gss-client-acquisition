# GSS Data Model — Draft v1: Decisions & Rationale

This accompanies `GSS_schema_v1.sql`. It records what was merged from where, what was deliberately left out, and what still needs a decision.

## Sources

- **PIMS** (`D:\Codegen\Claude\PIMS\Pims_App\schema.sql`) — the data model being cloned, per the project brief.
- **Tourism Management System** (`D:\Codegen\Claude\Tourism Management System\App\schema.sql`) — the architecture being cloned. TMS is itself PIMS reworked for multi-tenancy, so this draft applies that same rework directly to PIMS's modules, rather than re-deriving a multi-tenant design from scratch.

## What's in this draft

All six of GSS's named modules, built from PIMS's tables with TMS's multi-tenant rework applied throughout:

| GSS Module | Source | Notes |
|---|---|---|
| Organizations | PIMS `organizations`, enriched with TMS's `organization_addresses/emails/phones/reference_links` | See "Organizations enrichment" below |
| Contacts | PIMS Module A, as-is + `tenant_id` | Full CRUD, multi-value email/phone/address with history, self-referential assistant link |
| Documents & Knowledge Base | PIMS Module D, as-is + `tenant_id` | Content library, locations, keyword/hashtag tagging, knowledge-domain linking, contact links |
| Data Exchange | PIMS Module F, as-is + `tenant_id` | CSV import staging (batch → staging rows → commit), JSON/CSV/vCard export jobs |
| Table Maintenance | No dedicated schema — a generic CRUD blueprint over every tenant-scoped lookup table, same as TMS | Plus a separate Geography Maintenance screen for the four global tables (see below) |
| System Management | PIMS's System Management, restructured per TMS | `system_config` (PIMS's single-row config table) is gone — its job splits between `tenants` (DEK wrapping, retention) and `users` (password hash, recovery seed), since encryption is per-tenant and login is per-user now. Audit log, audit log archiving, and backups carried over. |

Plus **MODULE T** (tenants, users, roles) from TMS verbatim — this is the multi-tenancy foundation everything else sits on.

## What's excluded, and why

1. **Module B — Platforms & Subscriptions** (cloud platforms, subscriptions, software licenses, and every child/history table). Excluded per the project brief's explicit instruction.
2. **The `service_types` lookup table** ("Services" in PIMS). Excluded per the same instruction — it only ever classified `cloud_platforms`, so it has no purpose once Platforms & Subscriptions is gone regardless.
3. **`software_types` lookup**. Not named in the brief's exclusion note, but it exists solely to classify `desktop_software_licenses` (Platforms & Subscriptions), so it's dropped alongside that module for the same reason as `service_types`.
4. **Module C — Personal Accounts** (encrypted account number/CVV/PIN/password, its history table, `personal_account_types`). **This is an assumption, not an instruction** — the brief's NOTE only calls out Platforms & Subscriptions and Services by name. But Personal Accounts is also not one of GSS's six listed modules, so it's left out of this draft on that basis. **Flag if GSS actually wants something in this space** (e.g. storing client billing/account credentials) — it would reuse the same envelope-encryption pattern already in the schema.
5. **Everything TMS added beyond PIMS for tourism** (Points of Interest, Suppliers, Human Resources, Organization Intelligence, Inventory/Services/Products, Package Management, Knowledge Graph). None of this came from PIMS — it was TMS's own Phase 1.2+ build-out — so none of it is in scope for a PIMS clone.

## Enrichment kept from TMS: Organizations

PIMS treated `organizations` as a lightweight lookup off Contacts — one row, flat `full_address` / `phone` / `email` text columns, no history. TMS (building Suppliers as a real module) had already generalized that pattern into dedicated `organization_addresses`, `organization_emails`, `organization_phones` tables (multi-valued, own type lookups: `organization_address_types`, `organization_phone_types`), matching the shape Contacts already had.

Since GSS calls out **Organizations as a first-class module** — not just an attribute of Contacts — this draft keeps TMS's richer shape rather than PIMS's flat one. The original flat columns stay on `organizations` (unused by the UI) purely as a fallback so nothing is silently lost if old PIMS-shaped data is ever imported.

**Open question:** TMS doesn't track history on organization addresses/emails/phones (Organizations were reference/supplier data there, not an audited record the way a Contact is). For GSS, Organizations are prospects/clients being pursued for acquisition — arguably more deserving of a change history than a tourism supplier listing was. Worth a decision before this becomes real schema: add `organization_*_history` tables mirroring the Contact ones, or leave it as TMS had it?

## Enrichment kept from TMS: Geography

PIMS had a flat Country → State pair. TMS added a `regions` tier above Country and a `cities` tier below State, giving a full Region → Country → Province/State → City cascade on every address, with free-text fallbacks at the state and city level for geographies that aren't fully seeded. This draft keeps that cascade (applied to the Contacts address table `addresses` and the new `organization_addresses` table) since it's a strict improvement over PIMS's original pair and GSS is a fresh build, not a compatibility migration against existing PIMS data.

`regions`, `countries`, `states`, `country_phone_codes` (and now `cities`) stay **global** — shared real-world geography, not tenant opinion — exactly as TMS scoped them. Every other lookup table is tenant-scoped.

## Multi-tenancy & security model (from TMS, unchanged)

- **Auth split from field encryption.** `users.password_hash` is a standard per-user salted hash — ordinary login, independent of encryption. `tenants.dek_wrapped` is a per-**tenant** Data Encryption Key, wrapped under one system-level master key and unwrapped by the server once login succeeds — never derived from any user's password. This is what lets several users of one tenant (and a Tenant Admin resetting a teammate's password) all read the same encrypted data without re-encrypting anything.
- **`tenant_id` on every tenant-owned table**, so any query filters with a plain `WHERE tenant_id = ?` and one tenant can never see or modify another's data, even by guessing a record ID.
- **Roles**: SystemAdmin (cross-tenant, provisions tenants, whole-database backups) → TenantAdmin (manages users/settings within their own tenant) → User (day-to-day).
- **Known gap carried over from TMS**, worth closing before GSS goes beyond a trusted deployment: form-submitted foreign keys referencing another tenant's record by ID aren't currently tenant-validated (only URL-path-segment IDs are checked). TMS flagged this as a follow-up, not yet fixed there either.

## Table Maintenance — no dedicated schema

Table Maintenance (one of GSS's six named modules) doesn't need its own tables — in TMS it's a blueprint providing generic add/edit/deactivate CRUD over every tenant-scoped lookup table (Contact Categories, Titles, Suffixes, Professions, Contexts, Organization Types, Organization Address/Phone Types, Knowledge Domains/Subdomains, Content Types/Subtypes, Content Link Types). The four **global** geography tables (`regions`, `countries`, `states`, `cities`) get a separate **Geography Maintenance** screen instead, since editing one of those affects every tenant, not just the editor's own.

**Open question:** is a registry table wanted (e.g. listing which lookup tables are Table-Maintenance-editable, for a data-driven admin screen), or is a fixed set of screens (one per lookup table, as TMS built it) good enough for GSS's first pass?

## Next steps, not yet done

- Resolve the three open questions above (Personal Accounts, Organization history tracking, Table Maintenance registry).
- No forms/UI, `db.py`, `security/`, `auth/`, or blueprint code has been written yet — this is data-model only, per the "draft the model first" decision.
- No app scaffold exists yet in the GSS folder.
