"""
Per-user login password hashing — standard, independent of field encryption.

This is "is this the right password for this user" (a normal salted hash,
via Werkzeug — already a Flask dependency, so nothing new to add to
requirements.txt); security/crypto.py handles "what key encrypts this
tenant's sensitive columns," which is managed by the server, not derived
from any password.
"""
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config


def hash_password(password: str) -> str:
    return generate_password_hash(
        password,
        method=f"scrypt:{Config.SCRYPT_N}:{Config.SCRYPT_R}:{Config.SCRYPT_P}",
    )


def verify_password(password: str, stored_hash: str) -> bool:
    return check_password_hash(stored_hash, password)
