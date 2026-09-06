from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentgate.dataset.formats.json import dump
from agentgate.dataset.formats.xlsx import dump as dump_xlsx
from agentgate.dataset.loader import load_cases, load_dataset
from agentgate.domain import (
    Case,
    CaseTurn,
    Dataset,
    DatasetVersion,
    Equals,
    OutputExpectation,
    SkillRouteExpectation,
)


NOW = datetime(2026, 9, 6, tzinfo=UTC)


def document() -> dict[str, object]:
    dataset = Dataset(
        id="dataset",
        name="Loan evaluation",
        created_at=NOW,
        updated_at=NOW,
    )
    version = DatasetVersion(
        id="draft",
        dataset_id=dataset.id,
        dataset_name=dataset.name,
        cases=(
            Case(
                id="case",
                name="Multi-turn application",
                turns=(
                    CaseTurn(
                        id="turn-1",
                        input={"message": "I need a loan"},
                        expectations=(
                            SkillRouteExpectation(
                                id="route",
                                condition=Equals(expected="loan_approval"),
                            ),
                        ),
                    ),
                    CaseTurn(
                        id="turn-2",
                        input={"message": "The amount is 100000"},
                        expectations=(
                            OutputExpectation(
                                id="output",
                                path="status",
                                condition=Equals(expected="submitted"),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    return {
        "format": "agentgate.dataset",
        "format_version": 1,
        "dataset": dataset.model_dump(mode="json"),
        "version": version.model_dump(mode="json"),
    }


def test_load_json_builds_domain_objects_from_mapping_and_bytes() -> None:
    expected_dataset, expected_version = load_dataset(document(), "json")
    loaded_dataset, loaded_version = load_dataset(dump(document()), "json")

    assert loaded_dataset == expected_dataset
    assert loaded_version == expected_version
    assert loaded_version.cases[0].is_multi_turn
    assert isinstance(
        loaded_version.cases[0].turns[0].expectations[0],
        SkillRouteExpectation,
    )
    assert isinstance(
        loaded_version.cases[0].turns[1].expectations[0],
        OutputExpectation,
    )


def test_load_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="unsupported Dataset input format"):
        load_dataset(document(), "yaml")


def test_load_rejects_mismatched_dataset_identity() -> None:
    payload = document()
    version = dict(payload["version"])
    version["dataset_id"] = "another-dataset"
    version["content_sha256"] = ""
    payload["version"] = version

    with pytest.raises(ValueError, match="identities do not match"):
        load_dataset(payload, "json")


def test_load_rejects_unknown_expectation_kind() -> None:
    payload = document()
    version = dict(payload["version"])
    cases = list(version["cases"])
    case = dict(cases[0])
    turns = list(case["turns"])
    turn = dict(turns[0])
    turn["expectations"] = [{"id": "unknown", "kind": "not_supported"}]
    turns[0] = turn
    case["turns"] = turns
    cases[0] = case
    version["cases"] = cases
    version["content_sha256"] = ""
    payload["version"] = version

    with pytest.raises(ValidationError, match="Input tag 'not_supported'"):
        load_dataset(payload, "json")


def test_load_xlsx_cases_builds_current_multiturn_domain_objects() -> None:
    payload = document()
    expected = DatasetVersion.model_validate(payload["version"]).cases

    loaded = load_cases(
        dump_xlsx([case.model_dump(mode="json") for case in expected]),
        "xlsx",
    )

    assert loaded == expected
    assert loaded[0].is_multi_turn
    assert isinstance(loaded[0].turns[0].expectations[0], SkillRouteExpectation)


def test_load_cases_rejects_unknown_format() -> None:
    with pytest.raises(ValueError, match="unsupported Case input format"):
        load_cases(b"content", "csv")
