"""Process-local model credentials for the P1 user interface."""

from __future__ import annotations

from collections.abc import Callable
import os
import threading


class RuntimeCredentialStore:
    """Keep runtime overrides in memory and optionally fall back to the environment."""

    def __init__(self, fallback: Callable[[str], str | None] = os.getenv) -> None:
        self._fallback = fallback
        self._values: dict[str, str] = {}
        self._lock = threading.RLock()

    def get(self, credential_ref: str) -> str | None:
        with self._lock:
            value = self._values.get(credential_ref)
        return value if value is not None else self._fallback(credential_ref)

    def set(self, credential_ref: str, secret: str) -> None:
        with self._lock:
            self._values[credential_ref] = secret

    def delete(self, credential_ref: str) -> None:
        with self._lock:
            self._values.pop(credential_ref, None)

    def has_runtime_value(self, credential_ref: str) -> bool:
        with self._lock:
            return credential_ref in self._values
