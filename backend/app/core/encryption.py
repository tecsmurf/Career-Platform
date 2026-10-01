"""
Credential encryption for third-party integrations (email mailboxes).
====================================================================

Design:
- Fernet (AES-128-CBC + HMAC-SHA256, authenticated) via MultiFernet so keys
  can be rotated: the first key in EMAIL_ENCRYPTION_KEY encrypts, every key
  can decrypt.
- If EMAIL_ENCRYPTION_KEY is not configured, a key is derived from SECRET_KEY
  with HKDF and a purpose-specific label (domain separation), so the JWT
  signing key is never used directly as an encryption key.
- The encrypted payload is bound to its owner (user id + mailbox address).
  A ciphertext copied onto another user's row will fail to decrypt, so a
  database-level row swap cannot hand one user's mailbox to another.
- Errors never include key material or plaintext.
"""
import base64
import json
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

_PAYLOAD_VERSION = 1
_HKDF_SALT = b"career-platform/email-credentials"
_HKDF_INFO = b"career-platform/email-credentials/v1"


class CredentialDecryptionError(Exception):
    """Stored credentials could not be decrypted or failed the owner check."""


def _derive_key_from_secret(secret: str) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT, info=_HKDF_INFO)
    return base64.urlsafe_b64encode(hkdf.derive(secret.encode("utf-8")))


@lru_cache(maxsize=4)
def _cipher_for(keys: tuple[str, ...], secret_key: str) -> MultiFernet:
    if keys:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    return MultiFernet([Fernet(_derive_key_from_secret(secret_key))])


def _cipher() -> MultiFernet:
    return _cipher_for(tuple(settings.email_encryption_keys), settings.SECRET_KEY)


def _binding(user_id: int, account: str) -> dict:
    return {"uid": int(user_id), "acct": (account or "").strip().lower()}


def encrypt_credentials(secret_fields: dict, *, user_id: int, account: str) -> str:
    """Encrypt a dict of secret fields (e.g. {"password": ...}) for one owner."""
    payload = {"v": _PAYLOAD_VERSION, **_binding(user_id, account), "secret": secret_fields}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _cipher().encrypt(raw).decode("ascii")


def decrypt_credentials(token: str, *, user_id: int, account: str) -> dict:
    """Decrypt and verify ownership. Raises CredentialDecryptionError on any problem."""
    if not token:
        raise CredentialDecryptionError("no stored credentials")
    try:
        data = json.loads(_cipher().decrypt(token.encode("ascii")))
    except (InvalidToken, ValueError, TypeError, UnicodeError):
        raise CredentialDecryptionError("stored credentials could not be decrypted") from None

    expected = _binding(user_id, account)
    if (
        not isinstance(data, dict)
        or data.get("v") != _PAYLOAD_VERSION
        or data.get("uid") != expected["uid"]
        or data.get("acct") != expected["acct"]
        or not isinstance(data.get("secret"), dict)
    ):
        raise CredentialDecryptionError("stored credentials failed the ownership check")
    return data["secret"]
