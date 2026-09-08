"""Deterministic protected views of canonical execution traces."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import Any

from agentgate.domain import FrozenJsonObject, Trace, freeze_json
from agentgate.domain.base import FrozenJsonValue


REDACTION_MARKER = "[redacted]"

_KEY_SEPARATOR_PATTERN = re.compile(r"[^a-z0-9]+")
_INLINE_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer[_-]?token|client[_-]?secret|"
    r"password|refresh[_-]?token|secret[_-]?key|token)\s*([=:])\s*"
    r"(?:bearer\s+)?\S+"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_URL_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@"
)
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_EMAIL_PATTERN = re.compile(
    r"(?<![\w.+-])[\w.+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+(?![\w.-])",
    re.IGNORECASE,
)
_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")

_DEFAULT_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "address",
        "api_key",
        "authorization",
        "balance",
        "bank_account",
        "bank_account_number",
        "bearer_token",
        "birth_date",
        "card_number",
        "client_secret",
        "connection_string",
        "cookie",
        "credential_ref",
        "credentials",
        "credit_card",
        "credit_score",
        "customer_name",
        "cvc",
        "cvv",
        "date_of_birth",
        "dob",
        "email",
        "email_address",
        "environment_secret",
        "first_name",
        "full_name",
        "home_address",
        "iban",
        "income",
        "last_name",
        "loan_amount",
        "mobile",
        "mobile_number",
        "national_id",
        "nric",
        "passport",
        "passport_number",
        "password",
        "phone",
        "phone_number",
        "private_key",
        "refresh_token",
        "routing_number",
        "salary",
        "secret",
        "secret_key",
        "set_cookie",
        "signing_key",
        "ssh_key",
        "ssn",
        "tax_id",
        "token",
        "webhook_secret",
    }
)


def redact_trace(
    trace: Trace,
    *,
    additional_sensitive_keys: Collection[str] = (),
) -> Trace:
    """Return a protected Trace view without changing the canonical input."""

    sensitive_keys = _build_sensitive_keys(additional_sensitive_keys)

    spans = tuple(
        span.model_copy(
            update={
                "name": _redact_text(span.name),
                "attributes": _redact_object(span.attributes, sensitive_keys),
                "events": tuple(
                    _redact_object(event, sensitive_keys) for event in span.events
                ),
            }
        )
        for span in trace.spans
    )
    return trace.model_copy(
        update={
            "spans": spans,
            "turn_outcomes": _redact_object(trace.turn_outcomes, sensitive_keys),
            "final_output": _redact_object(trace.final_output, sensitive_keys),
            "final_state": _redact_object(trace.final_state, sensitive_keys),
        }
    )


def redact_value(
    value: object,
    *,
    additional_sensitive_keys: Collection[str] = (),
) -> FrozenJsonValue:
    """Return a protected immutable view of a JSON-compatible value."""

    sensitive_keys = _build_sensitive_keys(additional_sensitive_keys)
    return _redact_value(freeze_json(value), sensitive_keys)


def _build_sensitive_keys(additional_sensitive_keys: Collection[str]) -> set[str]:
    sensitive_keys = set(_DEFAULT_SENSITIVE_KEYS)
    for key in additional_sensitive_keys:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("additional sensitive keys must be nonblank strings")
        normalized_key = _normalize_key(key)
        if not normalized_key:
            raise ValueError("additional sensitive keys must contain letters or numbers")
        sensitive_keys.add(normalized_key)
    return sensitive_keys


def _redact_object(
    value: Mapping[str, Any], sensitive_keys: set[str]
) -> FrozenJsonObject:
    return FrozenJsonObject(
        {
            key: (
                REDACTION_MARKER
                if _is_sensitive_key(key, sensitive_keys)
                else _redact_value(item, sensitive_keys)
            )
            for key, item in value.items()
        }
    )


def _redact_value(value: Any, sensitive_keys: set[str]) -> Any:
    if isinstance(value, Mapping):
        return _redact_object(value, sensitive_keys)
    if isinstance(value, (list, tuple)):
        return tuple(_redact_value(item, sensitive_keys) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _normalize_key(key: str) -> str:
    return _KEY_SEPARATOR_PATTERN.sub("_", key.casefold()).strip("_")


def _is_sensitive_key(key: str, sensitive_keys: set[str]) -> bool:
    normalized = _normalize_key(key)
    return any(
        normalized == sensitive or normalized.endswith(f"_{sensitive}")
        for sensitive in sensitive_keys
    )


def _redact_text(value: str) -> str:
    value = _PRIVATE_KEY_PATTERN.sub(REDACTION_MARKER, value)
    value = _URL_CREDENTIAL_PATTERN.sub(r"\1[redacted]@", value)
    value = _INLINE_CREDENTIAL_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{REDACTION_MARKER}",
        value,
    )
    value = _BEARER_PATTERN.sub(REDACTION_MARKER, value)
    value = _EMAIL_PATTERN.sub(REDACTION_MARKER, value)
    return _CARD_PATTERN.sub(_redact_card_number, value)


def _redact_card_number(match: re.Match[str]) -> str:
    candidate = match.group(0)
    digits = "".join(character for character in candidate if character.isdigit())
    return REDACTION_MARKER if _passes_luhn(digits) else candidate


def _passes_luhn(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


__all__ = ["REDACTION_MARKER", "redact_trace", "redact_value"]
