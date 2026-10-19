"""Envelope encryption for secrets at rest.

Used for customer API keys, OAuth client secrets and connection
credentials.

    master key (env)  ->  wraps  ->  per-company data key  ->  encrypts  ->  secret

Per-company keys mean breaking one company does not expose the others.
The company id is passed as AES-GCM associated data, so a ciphertext
cannot be moved between companies — decryption fails rather than
silently succeeding with someone else's secret.
"""

from __future__ import annotations

import base64
import hashlib
import os
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_NONCE_BYTES = 12


def _master_key() -> bytes:
    """Derive a 32-byte key from the configured secret."""
    return hashlib.sha256(get_settings().encryption_key.encode()).digest()


def _derive_key(scope: str) -> bytes:
    """A distinct key per scope (a company id, or "platform").

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


def decrypt(blob: bytes, *, scope: str | uuid.UUID = "platform") -> str:
    scope_str = str(scope)
    nonce, ciphertext = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    plaintext = AESGCM(_derive_key(scope_str)).decrypt(nonce, ciphertext, scope_str.encode())
    return plaintext.decode()


def mask(secret: str) -> str:
    """What a stored secret looks like in an API response: never the value."""
    return f"{'•' * 6}{secret[-4:]}" if len(secret) >= 4 else "•" * 6


def fingerprint(secret: str) -> str:
    """A short non-reversible id, so two keys can be told apart in logs
    without the logs containing either of them."""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())[:8].decode()
