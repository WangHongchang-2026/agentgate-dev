import pytest
from pydantic import ValidationError

from agentgate.domain import (
    Case,
    CaseCategory,
    CaseDifficulty,
    CaseTurn,
    Equals,
    SkillRouteExpectation,
    ToolCallExpectation,
)


def test_case_has_typed_single_and_multi_turn_forms():
    single = Case(name="single", turns=(CaseTurn(id="only", input={"message": "hi"}),))
    case = Case(
        name="multi",
        category=CaseCategory.BOUNDARY,
        difficulty=CaseDifficulty.HARD,
        turns=(
            CaseTurn(id="one", input={"message": "申请贷款"}),
            CaseTurn(id="two", input={"amount": 80000}),
        ),
    )

    assert not single.is_multi_turn
    assert case.is_multi_turn
    assert case.turns[1].input["amount"] == 80000


@pytest.mark.parametrize(
    ("field", "value"),
    (("id", " "), ("name", "")),
)
def test_case_rejects_blank_identity(field, value):
    data = {"name": "case", "turns": (CaseTurn(input={"message": "hello"}),)}
    data[field] = value

    with pytest.raises(ValidationError):
        Case(**data)


def test_case_rejects_duplicate_turn_ids_and_tags():
    with pytest.raises(ValidationError, match="CaseTurn ids must be unique"):
        Case(
            name="duplicate turns",
            turns=(
                CaseTurn(id="same", input={"message": "first"}),
                CaseTurn(id="same", input={"message": "second"}),
            ),
        )

    with pytest.raises(ValidationError, match="tags must not contain duplicates"):
        Case(
            name="duplicate tags",
            turns=(CaseTurn(input={"message": "hello"}),),
            tags=("regression", "regression"),
        )


def test_case_rejects_blank_turn_id_and_duplicate_expectation_ids():
    with pytest.raises(ValidationError):
        CaseTurn(id=" ", input={"message": "hello"})

    with pytest.raises(ValidationError, match="Expectation ids must be unique"):
        Case(
            name="duplicate expectations",
            turns=(
                CaseTurn(
                    id="first",
                    input={"message": "hello"},
                    expectations=(
                        SkillRouteExpectation(
                            id="same", condition=Equals(expected="loan")
                        ),
                    ),
                ),
                CaseTurn(
                    id="second",
                    input={"message": "continue"},
                    expectations=(ToolCallExpectation(id="same", tool="credit"),),
                ),
            ),
        )
