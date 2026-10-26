"""Envelope encryption for secrets at rest.

Used for customer API keys, OAuth client secrets and connection
credentials.

    master key (env)  ->  wraps  ->  per-person data key  ->  encrypts  ->  secret

Per-person keys mean breaking one account does not expose the others.
The owner id is passed as AES-GCM associated data, so a ciphertext
cannot be moved between accounts — decryption fails rather than
silently succeeding with someone else's secret.
"""

from __future__ import annotations

import hashlib
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings
from app.core.errors import ValidationError

_NONCE_BYTES = 12


def _master_key() -> bytes:
    """Derive a 32-byte key from the configured secret."""
    return hashlib.sha256(get_settings().encryption_key.encode()).digest()


def _derive_key(scope: str) -> bytes:
    """A distinct key per scope (an owner id, or "platform").

    HKDF would be the textbook choice; SHA-256 over master + scope is
    sufficient here and keeps the dependency surface small.
    """
    return hashlib.sha256(_master_key() + scope.encode()).digest()


def encrypt(plaintext: str, *, scope: str | uuid.UUID = "platform") -> bytes:
    scope_str = str(scope)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_derive_key(scope_str)).encrypt(
        nonce, plaintext.encode(), scope_str.encode()
    )
    return nonce + ciphertext


class SecretUnreadableError(ValidationError):
    """A stored secret that no longer decrypts: it was saved under a
    different scope or master key. Said plainly, because the only fix is
    for its owner to enter it again."""

    def __init__(self) -> None:
        super().__init__("A saved key can no longer be read. Enter it again to keep using it.")


def decrypt(blob: bytes, *, scope: str | uuid.UUID = "platform") -> str:
    scope_str = str(scope)
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    try:
        plaintext = AESGCM(_derive_key(scope_str)).decrypt(nonce, ciphertext, scope_str.encode())
    except InvalidTag as exc:
        raise SecretUnreadableError() from exc
    return plaintext.decode()
