from __future__ import annotations

import pytest

from agentgate.run import can_retry_target_failure, retry_delay_seconds
from agentgate.run.target_protocol import TargetExecutionError


@pytest.mark.parametrize("code", ["rate_limited", "timeout", "unavailable"])
def test_retry_policy_accepts_classified_infrastructure_failures(code) -> None:
    error = TargetExecutionError(code, "temporary failure")

    assert can_retry_target_failure(error, retries_used=0, max_retries=1)


@pytest.mark.parametrize(
    "code",
    [
        "invalid_request",
        "target_not_found",
        "unauthorized",
        "rejected",
        "protocol_error",
        "cancelled",
    ],
)
def test_retry_policy_rejects_non_infrastructure_failures(code) -> None:
    error = TargetExecutionError(code, "terminal failure")

    assert not can_retry_target_failure(error, retries_used=0, max_retries=3)


def test_retry_policy_stops_after_allowance_is_used() -> None:
    error = TargetExecutionError("unavailable", "temporary failure")

    assert can_retry_target_failure(error, retries_used=1, max_retries=2)
    assert not can_retry_target_failure(error, retries_used=2, max_retries=2)
    assert not can_retry_target_failure(error, retries_used=0, max_retries=0)


@pytest.mark.parametrize(
    ("retries_used", "max_retries", "message"),
    [
        (-1, 1, "retries_used"),
        (0, -1, "max_retries"),
    ],
)
def test_retry_policy_rejects_invalid_counters(
    retries_used: int,
    max_retries: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        can_retry_target_failure(
            TargetExecutionError("timeout", "temporary failure"),
            retries_used=retries_used,
            max_retries=max_retries,
        )


def test_retry_delay_uses_bounded_exponential_schedule() -> None:
    assert [retry_delay_seconds(number) for number in range(1, 8)] == [
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        30.0,
        30.0,
    ]

    with pytest.raises(ValueError, match="at least 1"):
        retry_delay_seconds(0)
