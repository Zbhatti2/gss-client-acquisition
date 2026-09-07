"""
Central configuration for GSS (Client Acquisition Maximizing Platform).

Multi-tenant, multi-user, server-hosted architecture — cloned from the
Tourism Management System (TMS) Phase 1.1 per the GSS project brief. See
schema.sql MODULE T and security/crypto.py for how authentication (per-user)
and field encryption (per-tenant) are split.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)
EXPORTS_DIR = INSTANCE_DIR / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR = INSTANCE_DIR / "uploads" / "contacts"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
# Holding area for a business-card photo between "extract" and "save" (see
# blueprints/data_exchange.py) -- the review page carries forward only a
# short token pointing at a file here, never the image bytes themselves, so
# the save POST stays a normal small form submission (a full-size photo
# passed as base64 in a hidden field blows well past Werkzeug's 500KB
# max_form_memory_size for non-file fields). Swept of anything older than a
# few hours on each new extract, since an abandoned review page otherwise
# leaves its two images here forever.
PENDING_CARDS_DIR = INSTANCE_DIR / "uploads" / "business_card_pending"
PENDING_CARDS_DIR.mkdir(parents=True, exist_ok=True)
# Permanent home for an Organization Ad Listing's original photo(s) -- see
# organization_ad_photos in schema.sql and Organizations > Import Ad(s).
# Never normalized/downscaled: this is "maintaining the original ad".
AD_PHOTOS_DIR = INSTANCE_DIR / "uploads" / "organization_ads"
AD_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
# Same holding-area role as PENDING_CARDS_DIR above, but for the single-
# image Ad import's extract -> review -> save flow (blueprints/
# organizations.py) -- batch/zip ad import has no review step so it never
# uses this, it writes straight to AD_PHOTOS_DIR.
PENDING_ADS_DIR = INSTANCE_DIR / "uploads" / "organization_ad_pending"
PENDING_ADS_DIR.mkdir(parents=True, exist_ok=True)
BACKUPS_DIR = INSTANCE_DIR / "backups"
BACKUPS_DIR.mkdir(exist_ok=True)


class Config:
    # Flask's own signing key (session cookie, CSRF token signing). Generated
    # once and persisted to instance/secret_key so it survives restarts;
    # NOT the same thing as the field-encryption key(s) below.
    SECRET_KEY_PATH = INSTANCE_DIR / "secret_key"

    @staticmethod
    def get_secret_key() -> bytes:
        if Config.SECRET_KEY_PATH.exists():
            return Config.SECRET_KEY_PATH.read_bytes()
        key = os.urandom(32)
        Config.SECRET_KEY_PATH.write_bytes(key)
        return key

    # System-level master key used ONLY to wrap/unwrap each tenant's field-
    # encryption DEK (tenants.dek_wrapped). Deliberately a separate file from
    # SECRET_KEY_PATH above — different purpose, different blast radius if
    # ever rotated or leaked. Whoever holds this file (the server) can read
    # every tenant's encrypted fields, which is the correct trust boundary
    # for a server-hosted multi-user app (see schema.sql MODULE T).
    TENANT_MASTER_KEY_PATH = INSTANCE_DIR / "tenant_master.key"

    @staticmethod
    def get_tenant_master_key() -> bytes:
        from cryptography.fernet import Fernet
        if Config.TENANT_MASTER_KEY_PATH.exists():
            return Config.TENANT_MASTER_KEY_PATH.read_bytes()
        key = Fernet.generate_key()
        Config.TENANT_MASTER_KEY_PATH.write_bytes(key)
        return key

    DATABASE_PATH = str(INSTANCE_DIR / "gss.db")
    SCHEMA_PATH = str(BASE_DIR / "schema.sql")
    EXPORTS_DIR = str(EXPORTS_DIR)
    UPLOADS_DIR = str(UPLOADS_DIR)
    PENDING_CARDS_DIR = str(PENDING_CARDS_DIR)
    AD_PHOTOS_DIR = str(AD_PHOTOS_DIR)
    PENDING_ADS_DIR = str(PENDING_ADS_DIR)
    BACKUPS_DIR = str(BACKUPS_DIR)
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
    MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB — generous for a profile photo

    # scrypt KDF parameters used by security/passwords.py for user password
    # hashing (werkzeug's scrypt method). n is the memory/CPU cost factor.
    SCRYPT_N = 2 ** 14
    SCRYPT_R = 8
    SCRYPT_P = 1

    # Session inactivity timeout (minutes) — after this, the in-memory
    # tenant encryption key is dropped from this session and the user must
    # log in again.
    SESSION_TIMEOUT_MINUTES = 30
