from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from agentgate.domain import (
    Case,
    CaseTurn,
    DomainModel,
    EvaluatorSpec,
    FrozenJsonObject,
    StateExpectation,
    WithinRange,
    canonical_json,
    content_sha256,
    find_credential_path,
    freeze_json,
    normalize_utc,
    utcnow,
)


def test_expectation_and_evaluator_discriminated_unions():
    case = Case(
        id="case",
        name="case",
        turns=(
            CaseTurn(
                id="turn",
                input={"message": "hello"},
                expectations=(
                    {
                        "kind": "state",
                        "path": "status",
                        "condition": {"kind": "equals", "expected": "ok"},
                    },
                ),
            ),
        ),
    )
    assert isinstance(case.turns[0].expectations[0], StateExpectation)
    spec = TypeAdapter(EvaluatorSpec).validate_python(
        {
            "kind": "rule",
            "id": "state",
            "name": "state",
            "version": "1",
            "dimension": "state",
            "metric": "state_match",
            "implementation_id": "final_state",
        }
    )
    assert isinstance(spec, EvaluatorSpec)


def test_range_validation():
    with pytest.raises(ValidationError):
        WithinRange()
    with pytest.raises(ValidationError):
        WithinRange(minimum=2, maximum=1)


def test_frozen_json_rejects_non_string_keys_and_non_finite_numbers():
    with pytest.raises(TypeError, match="keys must be strings"):
        FrozenJsonObject({1: "integer key"})
    with pytest.raises(TypeError, match="keys must be strings"):
        canonical_json({1: "integer key"})

    class JsonModel(DomainModel):
        value: FrozenJsonObject

    with pytest.raises(ValidationError):
        JsonModel(value={1: "integer key"})

    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="must be finite"):
            freeze_json(value)


def test_canonical_json_and_hash_ignore_mapping_insertion_order():
    first = {"name": "loan", "config": {"model": "demo", "seed": 42}}
    second = {"config": {"seed": 42, "model": "demo"}, "name": "loan"}

    assert canonical_json(first) == canonical_json(second)
    assert content_sha256(first) == content_sha256(second)


def test_find_credential_path_handles_nested_objects_and_key_spelling():
    value = {"models": [{"auth": {"api-key": "plaintext"}}]}

    assert find_credential_path(value) == "models[0].auth.api-key"
    assert find_credential_path({"credential_ref": "vault/customer-key"}) is None


def test_utcnow_returns_timezone_aware_utc_timestamp():
    value = utcnow()

    assert value.tzinfo is UTC


def test_normalize_utc_converts_aware_timestamp_and_rejects_naive_timestamp():
    value = datetime(2026, 9, 5, 8, tzinfo=timezone(timedelta(hours=8)))

    assert normalize_utc(value, "created_at") == datetime(2026, 9, 5, tzinfo=UTC)
    with pytest.raises(ValueError, match="created_at must be timezone-aware"):
        normalize_utc(datetime(2026, 9, 5), "created_at")


def test_domain_model_validates_defaults_and_is_immutable():
    class InvalidDefault(DomainModel):
        count: int = "invalid"

    with pytest.raises(ValidationError):
        InvalidDefault()

    class ValidModel(DomainModel):
        count: int = 1

    model = ValidModel()
    with pytest.raises(ValidationError):
        model.count = 2
