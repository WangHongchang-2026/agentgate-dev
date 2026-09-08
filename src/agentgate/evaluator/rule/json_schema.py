"""Safe Draft 2020-12 JSON Schema validation for deterministic Rules."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import unquote

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from agentgate.domain.base import thaw_json


_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
_MAX_REASON_LENGTH = 400
_REFERENCE_KEYWORDS = frozenset({"$ref", "$dynamicRef", "$recursiveRef"})


class JsonSchemaConfigurationError(ValueError):
    """The configured schema cannot be safely evaluated by AgentGate."""


def _json_path(tokens: Iterable[object]) -> str:
    path = "$"
    for token in tokens:
        if isinstance(token, int):
            path += f"[{token}]"
        elif isinstance(token, str) and token.isidentifier():
            path += f".{token}"
        else:
            path += f"[{json.dumps(token, ensure_ascii=False)}]"
    return path


def _walk(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in _REFERENCE_KEYWORDS:
                yield key, child
            yield from _walk(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _walk(child)


def _resolve_json_pointer(document: Any, reference: str) -> None:
    if reference == "#":
        return
    if not reference.startswith("#/"):
        raise JsonSchemaConfigurationError(
            "JSON Schema references must use a local JSON Pointer"
        )

    current = document
    fragment = unquote(reference[1:])
    for encoded_token in fragment.split("/")[1:]:
        token = encoded_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
            continue
        if isinstance(current, list):
            try:
                index = int(token)
                current = current[index]
                continue
            except (ValueError, IndexError):
                pass
        raise JsonSchemaConfigurationError(
            f"JSON Schema local reference does not resolve: {reference}"
        )


def _validator(schema: Mapping[str, Any]) -> Draft202012Validator:
    plain_schema = thaw_json(schema)
    if not isinstance(plain_schema, dict):
        raise JsonSchemaConfigurationError("JSON Schema must be an object")

    declared_draft = plain_schema.get("$schema")
    if declared_draft is not None and declared_draft != _DRAFT_2020_12:
        raise JsonSchemaConfigurationError(
            "JSON Schema must use Draft 2020-12"
        )
    try:
        Draft202012Validator.check_schema(plain_schema)
    except SchemaError as exc:
        path = _json_path(exc.path)
        raise JsonSchemaConfigurationError(
            f"invalid Draft 2020-12 JSON Schema at {path}"
        ) from None

    for keyword, reference in _walk(plain_schema):
        if keyword != "$ref":
            raise JsonSchemaConfigurationError(
                f"JSON Schema {keyword} references are not supported"
            )
        if not isinstance(reference, str):
            raise JsonSchemaConfigurationError(
                "JSON Schema $ref must be a string"
            )
        _resolve_json_pointer(plain_schema, reference)
    return Draft202012Validator(plain_schema)


def validate_json_schema(schema: Mapping[str, Any]) -> None:
    """Reject an invalid, unsupported, or externally resolving schema."""

    _validator(schema)


def _error_key(error: ValidationError) -> tuple[str, str, str]:
    return (
        _json_path(error.absolute_path),
        _json_path(error.absolute_schema_path),
        str(error.validator or "validation"),
    )


def json_schema_failure_reason(
    actual: Any,
    schema: Mapping[str, Any],
) -> str | None:
    """Return a safe deterministic reason for the first schema violation."""

    validator = _validator(schema)
    instance = thaw_json(actual)
    errors = sorted(validator.iter_errors(instance), key=_error_key)
    if not errors:
        return None
    first = errors[0]
    reason = (
        f"JSON Schema violation at {_json_path(first.absolute_path)} "
        f"({first.validator or 'validation'})"
    )
    if len(reason) <= _MAX_REASON_LENGTH:
        return reason
    return f"{reason[: _MAX_REASON_LENGTH - 1].rstrip()}…"


__all__ = [
    "JsonSchemaConfigurationError",
    "json_schema_failure_reason",
    "validate_json_schema",
]
