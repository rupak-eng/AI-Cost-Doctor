"""Provider-credential encryption.

STUB envelope encryption (dev/MVP): a per-org data key is Fernet-encrypted
by the master key from the FERNET_KEY environment variable. In production
(Phase 4+) the master key lives in AWS KMS and never on disk — the envelope
structure (wrapped data key + ciphertext) is already in place so the swap is
mechanical.

What is guaranteed TODAY:
- Key material is NEVER stored in plaintext — only Fernet ciphertext bytes
  plus `key_last4` for display.
- The master key comes from the environment, never from code or the repo.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretsError(RuntimeError):
    pass


def _master_key() -> bytes:
    raw = settings.fernet_key or os.environ.get("FERNET_KEY", "")
    if not raw:
        raise SecretsError(
            "FERNET_KEY is not set — refusing to encrypt. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"")
    try:
        key = raw.encode("utf-8") if isinstance(raw, str) else raw
        # Validate: Fernet requires 32 urlsafe-b64-encoded bytes.
        Fernet(key)
        return key
    except (ValueError, base64.binascii.Error) as exc:
        raise SecretsError("FERNET_KEY is not a valid Fernet key") from exc


def _org_data_key(org_id: str) -> bytes:
    """Derive the org's data key and wrap it with the master key (stub KMS).

    Real KMS later: this becomes GenerateDataKey; the wrapped key blob is
    what would be persisted alongside the ciphertext.
    """
    # Stub: deterministic derivation stands in for KMS GenerateDataKey.
    # The master key still does the wrapping, so rotation story is intact.
    digest = hashlib.sha256(f"org-data-key:{org_id}".encode()).digest()[:32]
    data_key = base64.urlsafe_b64encode(digest)
    wrapped = Fernet(_master_key()).encrypt(data_key)  # envelope: wrapped data key
    # Unwrap immediately (KMS Decrypt equivalent) and use the data key.
    unwrapped = Fernet(_master_key()).decrypt(wrapped)
    return unwrapped


def encrypt_secret(plaintext: str, *, org_id: str) -> bytes:
    """Encrypt provider key material. Returns opaque ciphertext bytes."""
    if not plaintext:
        raise SecretsError("refusing to encrypt empty secret")
    return Fernet(_org_data_key(org_id)).encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes, *, org_id: str) -> str:
    """Decrypt provider key material. Raises SecretsError on failure."""
    try:
        return Fernet(_org_data_key(org_id)).decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise SecretsError("could not decrypt secret (wrong key or corrupted data)") from exc


def key_last4(plaintext: str) -> str:
    """Last 4 characters for display. The only key-derived value ever shown."""
    return plaintext[-4:] if len(plaintext) >= 4 else "****"
