"""Shared immutable domain-model utilities."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict
from pydantic_core import core_schema


_CREDENTIAL_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer_token",
    "client_secret",
    "password",
    "secret_key",
}


def utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def normalize_utc(value: datetime, field_name: str) -> datetime:
    """Return a timezone-aware datetime normalized to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def require_non_blank(value: str, field_name: str) -> str:
    """Return a nonblank string or raise a field-specific validation error."""

    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def find_credential_path(value: Any, prefix: str = "") -> str | None:
    """Return the first path whose key indicates an embedded credential."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key.lower().replace("-", "_") in _CREDENTIAL_KEYS:
                return path
            found = find_credential_path(item, path)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = find_credential_path(item, f"{prefix}[{index}]")
            if found:
                return found
    return None


class FrozenJsonObject(Mapping[str, Any]):
    """Recursively immutable JSON object with Pydantic serialization support."""

    __slots__ = ("_data",)

    def __init__(self, value: Mapping[str, Any] | None = None) -> None:
        source = value or {}
        if any(not isinstance(key, str) for key in source):
            raise TypeError("JSON object keys must be strings")
        self._data = {key: freeze_json(item) for key, item in source.items()}

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"FrozenJsonObject({self._data!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Mapping) and dict(self.items()) == dict(other.items())

    def to_dict(self) -> dict[str, Any]:
        return {key: thaw_json(value) for key, value in self._data.items()}

    @classmethod
    def __get_pydantic_core_schema__(cls, _source: Any, _handler: Any) -> core_schema.CoreSchema:
        return core_schema.no_info_after_validator_function(
            lambda value: value if isinstance(value, cls) else cls(value),
            core_schema.dict_schema(
                core_schema.str_schema(strict=True), core_schema.any_schema()
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda value: value.to_dict(), when_used="always"
            ),
        )


JsonScalar: TypeAlias = None | bool | int | float | str
FrozenJsonValue: TypeAlias = JsonScalar | FrozenJsonObject | tuple["FrozenJsonValue", ...]


def freeze_json(value: Any) -> FrozenJsonValue:
    """Convert a JSON-compatible value into its recursively immutable form."""

    if isinstance(value, FrozenJsonObject):
        return value
    if isinstance(value, Mapping):
        return FrozenJsonObject(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON numbers must be finite")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")


def thaw_json(value: Any) -> Any:
    """Convert an immutable JSON value into ordinary dictionaries and lists."""

    if isinstance(value, FrozenJsonObject):
        return value.to_dict()
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON object keys must be strings")
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [thaw_json(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize a JSON-compatible value deterministically for comparison and hashing."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_sha256(value: Any) -> str:
    """Return the SHA-256 digest of the canonical JSON representation of a value."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class DomainModel(BaseModel):
    """Base for immutable domain values that reject undeclared fields."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        arbitrary_types_allowed=True,
    )
