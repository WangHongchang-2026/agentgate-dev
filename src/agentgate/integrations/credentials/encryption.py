"""Authenticated encryption for persisted API Key material."""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_AAD = b"agentgate:api-key:v1"
_NONCE_BYTES = 12
_PREFIX = "v1."


class ApiKeyEncryptionError(ValueError):
    """Safe failure raised when encrypted API Key material is invalid."""


class ApiKeyEncryptor:
    """Encrypt and decrypt API Keys with one process-provided master key."""

    __slots__ = ("_cipher",)

    def __init__(self, master_key: bytes) -> None:
        if not isinstance(master_key, bytes) or len(master_key) != 32:
            raise ValueError("API Key master key must contain exactly 32 bytes")
        self._cipher = AESGCM(master_key)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<redacted>)"

    def encrypt(self, plaintext: str) -> str:
        """Return a versioned encrypted payload for one nonblank API Key."""

        if not isinstance(plaintext, str) or not plaintext.strip():
            raise ValueError("API Key plaintext must be a nonblank string")
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(nonce, plaintext.encode("utf-8"), _AAD)
        encoded = base64.urlsafe_b64encode(nonce + ciphertext).rstrip(b"=")
        return _PREFIX + encoded.decode("ascii")

    def decrypt(self, encrypted: str) -> str:
        """Return plaintext or raise one sanitized authentication failure."""

        try:
            if not isinstance(encrypted, str) or not encrypted.startswith(_PREFIX):
                raise ValueError
            encoded = encrypted.removeprefix(_PREFIX).encode("ascii")
            padding = b"=" * (-len(encoded) % 4)
            payload = base64.b64decode(
                encoded + padding,
                altchars=b"-_",
                validate=True,
            )
            canonical = base64.urlsafe_b64encode(payload).rstrip(b"=")
            if encoded != canonical:
                raise ValueError
            if len(payload) <= _NONCE_BYTES + 16:
                raise ValueError
            nonce = payload[:_NONCE_BYTES]
            ciphertext = payload[_NONCE_BYTES:]
            plaintext = self._cipher.decrypt(nonce, ciphertext, _AAD)
            return plaintext.decode("utf-8")
        except (
            InvalidTag,
            UnicodeDecodeError,
            UnicodeEncodeError,
            binascii.Error,
            ValueError,
        ):
            raise ApiKeyEncryptionError(
                "encrypted API Key cannot be decrypted"
            ) from None


__all__ = ["ApiKeyEncryptionError", "ApiKeyEncryptor"]
