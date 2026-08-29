"""
Encryption utilities for sensitive data (email passwords).

Uses Fernet symmetric encryption with a key derived from SECRET_KEY.
The encrypted value is stored in the database — even if someone
reads the database directly (e.g. Neon console), they see gibberish.
"""
import base64
import hashlib

from cryptography.fernet import Fernet

from app.core.config import settings


def _get_fernet() -> Fernet:
    """Derive a Fernet key from SECRET_KEY."""
    # Fernet needs a 32-byte base64-encoded key
    # Derive it deterministically from SECRET_KEY
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plain_text: str) -> str:
    """Encrypt a string. Returns base64-encoded ciphertext."""
    if not plain_text:
        return ""
    f = _get_fernet()
    return f.encrypt(plain_text.encode()).decode()


def decrypt(encrypted_text: str) -> str:
    """Decrypt a base64-encoded ciphertext. Returns plain string."""
    if not encrypted_text:
        return ""
    f = _get_fernet()
    return f.decrypt(encrypted_text.encode()).decode()
