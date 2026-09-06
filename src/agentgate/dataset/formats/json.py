"""Canonical JSON syntax for Dataset exchange."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


FORMAT_NAME = "agentgate.dataset"
FORMAT_VERSION = 1
_ENVELOPE_KEYS = {"format", "format_version", "dataset", "version"}


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _validate_envelope(document: Mapping[str, Any]) -> None:
    keys = set(document)
    missing = _ENVELOPE_KEYS - keys
    if missing:
        raise ValueError(f"Dataset JSON envelope is missing: {', '.join(sorted(missing))}")
    unexpected = keys - _ENVELOPE_KEYS
    if unexpected:
        raise ValueError(
            f"Dataset JSON envelope has unexpected fields: {', '.join(sorted(unexpected))}"
        )
    if document["format"] != FORMAT_NAME:
        raise ValueError(f"unsupported Dataset format: {document['format']!r}")
    if type(document["format_version"]) is not int:
        raise ValueError("Dataset format_version must be an integer")
    if document["format_version"] != FORMAT_VERSION:
        raise ValueError(
            f"unsupported Dataset format version: {document['format_version']!r}"
        )
    if not isinstance(document["dataset"], Mapping):
        raise ValueError("Dataset JSON envelope field 'dataset' must be an object")
    if not isinstance(document["version"], Mapping):
        raise ValueError("Dataset JSON envelope field 'version' must be an object")


def parse(source: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    """Parse JSON input and return a validated Dataset envelope."""

    if isinstance(source, Mapping):
        document = dict(source)
    else:
        document = json.loads(source, object_pairs_hook=_object_without_duplicates)
    if not isinstance(document, dict):
        raise ValueError("Dataset JSON document must be an object")
    _validate_envelope(document)
    return document


def dump(document: Mapping[str, Any]) -> bytes:
    """Encode a validated Dataset envelope as deterministic UTF-8 JSON."""

    _validate_envelope(document)
    return json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

