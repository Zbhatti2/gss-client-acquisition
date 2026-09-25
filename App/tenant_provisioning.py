"""
Shared "create a brand new tenant + its first Tenant Admin" logic.

Two entry points call this:
  * The self-service /setup wizard (auth/routes.py) -- reached before
    anyone has logged in, for the very first tenant or a manual fallback.
  * The SystemAdmin-facing Tenant Management console
    (blueprints/tenants_admin.py) -- the normal way additional tenants get
    created once GSS is actually running multi-tenant.

Kept as one function so the two entry points can never drift apart on what
"provisioning a tenant" actually does (DEK generation/wrapping, the first
TenantAdmin row, seeding that tenant's lookup tables).
"""
import re
import secrets


def slugify_tenant_code(tenant_name: str) -> str:
    """'Acme Corp' -> 'ACME_CORP'. The tenant's short internal code (used
    internally -- exports, future subdomains -- never shown as "the" name
    to end users) when nothing more specific is supplied."""
    code = re.sub(r"[^A-Za-z0-9]+", "_", tenant_name.strip()).strip("_").upper()
    return code or secrets.token_hex(4).upper()


def provision_tenant(db, tenant_name: str, username: str, display_name: str, password: str,
                     tenant_code: str = None, must_change_password: bool = False):
    """Creates a new tenant (with a fresh, wrapped DEK), its first
    TenantAdmin user, and seeds that tenant's lookup tables. Returns
    (tenant_id, seed_phrase) -- the seed phrase is generated fresh on every
    call; showing it to whoever just ran this (once, then discarding it) is
    the caller's job.

    must_change_password defaults to False because /setup's caller chose
    this password themselves (nothing to force a change on); pass True from
    an admin console where someone ELSE is handing this password to the new
    admin (see blueprints/tenants_admin.py) -- same reasoning as
    blueprints/users.py's new_user().

    Does NOT validate its inputs (blank name, weak password, duplicate
    username) -- both call sites validate before calling this, since the
    right error messages differ slightly between a first-run wizard and an
    admin console."""
    from db import next_account_number
    from security import crypto
    from security.passwords import hash_password
    from security.wordlist import generate_seed_phrase, hash_phrase

    dek = crypto.new_tenant_dek()
    dek_wrapped = crypto.wrap_tenant_dek(dek)
    tenant_code = tenant_code or slugify_tenant_code(tenant_name)
    account_number = next_account_number(db)

    cur = db.execute(
        "INSERT INTO tenants (tenant_code, tenant_name, dek_wrapped, account_number) VALUES (?, ?, ?, ?)",
        (tenant_code, tenant_name, dek_wrapped, account_number),
    )
    tenant_id = cur.lastrowid

    seed_phrase_value = generate_seed_phrase()
    db.execute(
        """INSERT INTO users (tenant_id, username, display_name, password_hash, role, recovery_seed_hash, must_change_password)
           VALUES (?, ?, ?, ?, 'TenantAdmin', ?, ?)""",
        (tenant_id, username, display_name, hash_password(password), hash_phrase(seed_phrase_value),
         1 if must_change_password else 0),
    )
    db.commit()

    from seed_data import seed_lookup_tables, clone_pipeline_templates_to_tenant
    seed_lookup_tables(db, tenant_id)

    # Client Acquisition pipeline templates: cloned from the reserved
    # GSS_PLATFORM tenant's master copies (db.py's
    # _migration_client_acquisition_module seeds those), same
    # clone-at-provisioning pattern as every other per-tenant lookup table
    # above -- a no-op if the platform tenant or its templates don't exist
    # yet (e.g. a database provisioned before that migration ran once).
    platform_row = db.execute("SELECT tenant_id FROM tenants WHERE tenant_code = 'GSS_PLATFORM'").fetchone()
    if platform_row and platform_row["tenant_id"] != tenant_id:
        clone_pipeline_templates_to_tenant(db, platform_row["tenant_id"], tenant_id)
    db.commit()

    return tenant_id, seed_phrase_value
