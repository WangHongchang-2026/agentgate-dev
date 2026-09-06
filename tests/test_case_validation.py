import pytest

from agentgate.case import DatasetValidationError, validate_dataset_version
from agentgate.domain import Case, CaseTurn, DatasetVersion, Equals, StateExpectation


def test_validation_rejects_empty_dataset():
    with pytest.raises(DatasetValidationError) as empty:
        validate_dataset_version(DatasetVersion(dataset_id="dataset"))
    assert empty.value.issues[0].path == "cases"


def test_validation_accepts_multi_turn_expectations():
    version = DatasetVersion(
        dataset_id="dataset",
        cases=(
            Case(
                name="multi",
                turns=(
                    CaseTurn(input={"message": "hello"}),
                    CaseTurn(
                        input={"skill": "credit_inquiry", "application_id": "A-1"},
                        expectations=(
                            StateExpectation(
                                path="risk", condition=Equals(expected="low")
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )
    validate_dataset_version(version)
