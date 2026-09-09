"""Process configuration for API Key encryption."""

from __future__ import annotations

import base64
import binascii
import os
import re
from collections.abc import Mapping

from .encryption import ApiKeyEncryptor


API_KEY_ENCRYPTION_KEY_ENV = "AGENTGATE_API_KEY_ENCRYPTION_KEY"
_URLSAFE_BASE64 = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def _decode_master_key(value: object) -> bytes:
    try:
        if not isinstance(value, str):
            raise ValueError
        encoded = value.strip()
        if not _URLSAFE_BASE64.fullmatch(encoded):
            raise ValueError
        raw = encoded.rstrip("=").encode("ascii")
        padding = b"=" * (-len(raw) % 4)
        decoded = base64.b64decode(
            raw + padding,
            altchars=b"-_",
            validate=True,
        )
        if len(decoded) != 32:
            raise ValueError
        return decoded
    except (UnicodeEncodeError, binascii.Error, ValueError):
        raise ValueError(
            f"{API_KEY_ENCRYPTION_KEY_ENV} must be URL-safe Base64 "
            "for exactly 32 bytes"
        ) from None


def load_api_key_encryptor(
    environ: Mapping[str, str] | None = None,
) -> ApiKeyEncryptor:
    """Build an encryptor from one required process-level master key."""

    source = os.environ if environ is None else environ
    if API_KEY_ENCRYPTION_KEY_ENV not in source:
        raise ValueError(f"{API_KEY_ENCRYPTION_KEY_ENV} is required")
    return ApiKeyEncryptor(
        _decode_master_key(source[API_KEY_ENCRYPTION_KEY_ENV])
    )


__all__ = ["API_KEY_ENCRYPTION_KEY_ENV", "load_api_key_encryptor"]
