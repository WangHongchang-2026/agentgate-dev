"""Pure retry policy for classified Target infrastructure failures."""

from __future__ import annotations

from .target_protocol import TargetExecutionError


_RETRYABLE_ERROR_CODES = frozenset({"rate_limited", "timeout", "unavailable"})


def can_retry_target_failure(
    error: TargetExecutionError,
    *,
    retries_used: int,
    max_retries: int,
) -> bool:
    """Return whether one classified Target failure may be attempted again."""

    if retries_used < 0:
        raise ValueError("retries_used must not be negative")
    if max_retries < 0:
        raise ValueError("max_retries must not be negative")
    return error.code in _RETRYABLE_ERROR_CODES and retries_used < max_retries


def retry_delay_seconds(retry_number: int) -> float:
    """Return bounded exponential delay for a one-based retry number."""

    if retry_number < 1:
        raise ValueError("retry_number must be at least 1")
    if retry_number >= 6:
        return 30.0
    return float(2 ** (retry_number - 1))
