import json
from itertools import combinations

import httpx
import pytest

from agentgate.application.evaluator_management import (
    DEFAULT_EVALUATOR_MANAGEMENT,
    EvaluatorManagement,
    build_default_evaluator_management,
)
from agentgate.demo.loan import LOAN_DATASET_VERSION
from agentgate.domain import (
    Case,
    CaseTurn,
    CombinationPolicy,
    DatasetVersion,
    Equals,
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSpec,
    MatchesJsonSchema,
    Outcome,
    OutputExpectation,
    PolicyExpectation,
    StateExpectation,
    Trace,
)
from agentgate.evaluator.models import (
    DuplicateEvaluatorId,
    MissingEvaluatorDependency,
    UnknownEvaluator,
)
from agentgate.evaluator.rule import FinalOutputEvaluator, FinalStateEvaluator
from agentgate.evaluator.rule.json_schema import JsonSchemaConfigurationError
from agentgate.evaluator.rule.policy import UnsupportedPolicy
from agentgate.integrations.model_providers import OpenAICompatibleModelClient


def spec(
    evaluator_id: str,
    implementation_id: str,
    *,
    dimension: str = "quality",
    metric: str | None = None,
) -> EvaluatorSpec:
    return EvaluatorSpec(
        id=evaluator_id,
        name=evaluator_id,
        implementation_id=implementation_id,
        dimension=dimension,
        metric=metric or evaluator_id,
    )


def draft_dataset(*expectations) -> DatasetVersion:
    return DatasetVersion(
        dataset_id="dataset",
        cases=(
            Case(
                id="case",
                name="case",
                turns=(
                    CaseTurn(
                        id="turn",
                        input={"message": "start"},
                        expectations=expectations,
                    ),
                ),
            ),
        ),
    )


def test_builtin_catalog_and_composition_are_exact() -> None:
    specs = DEFAULT_EVALUATOR_MANAGEMENT.available_specs

    assert tuple(item.id for item in specs) == (
        "skill-routing",
        "required-tool",
        "forbidden-tool",
        "tool-arguments",
        "final-state",
        "final-output",
        "policy-compliance",
    )
    assert all(item.kind == EvaluatorKind.RULE for item in specs)
    assert all(item.implementation_version == "1" for item in specs)
    assert all(item.config == {} for item in specs)
    assert specs[2].severity.value == "blocking"
    assert specs[6].severity.value == "blocking"


def test_default_builder_preserves_rule_only_catalog() -> None:
    management = build_default_evaluator_management()

    assert management.available_specs == DEFAULT_EVALUATOR_MANAGEMENT.available_specs


@pytest.mark.parametrize(
    "provided",
    [
        combination
        for size in (1, 2)
        for combination in combinations(
            ("judge_client", "judge_model_id", "judge_credential_ref"),
            size,
        )
    ],
)
def test_default_builder_rejects_partial_judge_configuration(
    provided: tuple[str, ...],
) -> None:
    values = {
        "judge_client": object(),
        "judge_model_id": "judge-model",
        "judge_credential_ref": "env:AGENTGATE_JUDGE_API_KEY",
    }

    with pytest.raises(ValueError, match="must be provided together"):
        build_default_evaluator_management(
            **{name: values[name] for name in provided},
        )


def test_constructor_copies_composition_and_rejects_misalignment() -> None:
    output_spec = spec("output", "final_output")
    implementations = {("final_output", "1"): FinalOutputEvaluator()}
    management = EvaluatorManagement((output_spec,), implementations)
    implementations.clear()

    selected = management.select(None)
    case = Case(
        id="case",
        name="case",
        turns=(
            CaseTurn(
                id="turn",
                input={"message": "start"},
                expectations=(
                    OutputExpectation(condition=Equals(expected={"answer": "ok"})),
                ),
            ),
        ),
    )
    results = management.evaluate_case(
        case,
        Trace(
            trace_id="0" * 32,
            run_id="run",
            case_id="case",
            spans=(),
            final_output={"answer": "ok"},
        ),
        selected,
    )

    assert results[0].outcome == Outcome.PASS
    with pytest.raises(ValueError, match="at least one"):
        EvaluatorManagement((output_spec,), {})
    with pytest.raises(UnknownEvaluator, match="unknown evaluator implementation"):
        EvaluatorManagement(
            (output_spec,),
            {("other", "1"): FinalOutputEvaluator()},
        )
    with pytest.raises(UnknownEvaluator, match="unreferenced"):
        EvaluatorManagement(
            (output_spec,),
            {
                ("final_output", "1"): FinalOutputEvaluator(),
                ("final_state", "1"): FinalStateEvaluator(),
            },
        )
    with pytest.raises(DuplicateEvaluatorId, match="unique"):
        EvaluatorManagement((output_spec, output_spec), {
            ("final_output", "1"): FinalOutputEvaluator(),
        })


def test_selection_preserves_order_and_rejects_invalid_requests() -> None:
    selected = DEFAULT_EVALUATOR_MANAGEMENT.select(
        ("final-output", "skill-routing")
    )

    assert tuple(item.id for item in selected) == (
        "final-output",
        "skill-routing",
    )
    assert DEFAULT_EVALUATOR_MANAGEMENT.select(None) is (
        DEFAULT_EVALUATOR_MANAGEMENT.available_specs
    )
    with pytest.raises(ValueError, match="at least one"):
        DEFAULT_EVALUATOR_MANAGEMENT.select(())
    with pytest.raises(DuplicateEvaluatorId, match="unique"):
        DEFAULT_EVALUATOR_MANAGEMENT.select(("final-output", "final-output"))
    with pytest.raises(UnknownEvaluator, match="unknown"):
        DEFAULT_EVALUATOR_MANAGEMENT.select(("unknown",))


def test_validates_builtin_demo_and_rejects_catalog_drift() -> None:
    selected = DEFAULT_EVALUATOR_MANAGEMENT.available_specs

    assert DEFAULT_EVALUATOR_MANAGEMENT.validate_plan(
        LOAN_DATASET_VERSION,
        selected,
    ) is None
    drifted_data = selected[0].model_dump(
        mode="json",
        exclude={"content_sha256"},
    )
    drifted_data["name"] = "Drifted"
    drifted = EvaluatorSpec.model_validate(drifted_data)
    with pytest.raises(ValueError, match="content mismatch"):
        DEFAULT_EVALUATOR_MANAGEMENT.validate_plan(
            LOAN_DATASET_VERSION,
            (drifted, *selected[1:]),
        )


def test_preflight_accepts_json_schema_and_rejects_unsupported_policies() -> None:
    state_specs = DEFAULT_EVALUATOR_MANAGEMENT.select(("final-state",))
    schema_dataset = draft_dataset(
        StateExpectation(
            path="value",
            condition=MatchesJsonSchema(json_schema={"type": "string"}),
        )
    )
    policy_dataset = draft_dataset(PolicyExpectation(policy_id="unknown_policy"))

    assert DEFAULT_EVALUATOR_MANAGEMENT.validate_plan(
        schema_dataset,
        state_specs,
    ) is None
    with pytest.raises(UnsupportedPolicy, match="unknown_policy"):
        DEFAULT_EVALUATOR_MANAGEMENT.validate_plan(policy_dataset, state_specs)


@pytest.mark.parametrize(
    "json_schema, message",
    (
        ({"type": "private-invalid-type"}, "invalid Draft 2020-12"),
        ({"$ref": "https://schemas.example/value.json"}, "local JSON Pointer"),
    ),
)
def test_preflight_rejects_invalid_or_unsafe_json_schemas(
    json_schema: dict[str, object],
    message: str,
) -> None:
    dataset = draft_dataset(
        StateExpectation(
            path="value",
            condition=MatchesJsonSchema(json_schema=json_schema),
        )
    )
    state_specs = DEFAULT_EVALUATOR_MANAGEMENT.select(("final-state",))

    with pytest.raises(JsonSchemaConfigurationError, match=message):
        DEFAULT_EVALUATOR_MANAGEMENT.validate_plan(dataset, state_specs)


def test_preflight_rejects_metric_dimension_conflicts() -> None:
    first = spec("first", "final_state", dimension="state", metric="same")
    second = spec("second", "final_state", dimension="tool_use", metric="same")
    management = EvaluatorManagement(
        (first, second),
        {("final_state", "1"): FinalStateEvaluator()},
    )

    with pytest.raises(ValueError, match="cannot belong"):
        management.validate_plan(DatasetVersion(dataset_id="dataset"), (first, second))


class HybridImplementation:
    kind = EvaluatorKind.HYBRID
    implementation_id = "hybrid"
    implementation_version = "1"

    def applies_to(self, spec, turn):
        return True

    def evaluate(self, spec, turn, trace, resolve):
        raise AssertionError("preflight must reject missing children")


def test_preflight_rejects_missing_selected_dependencies() -> None:
    hybrid = EvaluatorSpec(
        id="hybrid",
        name="hybrid",
        kind=EvaluatorKind.HYBRID,
        dimension="quality",
        metric="hybrid",
        implementation_id="hybrid",
        children=(
            EvaluatorRef(evaluator_id="rule", evaluator_version="1"),
            EvaluatorRef(evaluator_id="judge", evaluator_version="1"),
        ),
        combination=CombinationPolicy.ALL,
    )
    management = EvaluatorManagement(
        (hybrid,),
        {("hybrid", "1"): HybridImplementation()},
    )

    with pytest.raises(MissingEvaluatorDependency, match="rule"):
        management.validate_plan(DatasetVersion(dataset_id="dataset"), (hybrid,))


def test_composes_and_executes_judge_through_application_boundary() -> None:
    sent_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "judge-request",
                "model": "resolved-judge-model",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "verdict": "pass",
                                    "score": 0.9,
                                    "confidence": 0.95,
                                    "reason": "The answer satisfies the rubric",
                                    "violations": [],
                                }
                            )
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    model_client = OpenAICompatibleModelClient(
        provider_id="company-llm",
        base_url="https://models.example/v1",
        api_key="resolved-secret",
        http_client=http_client,
    )
    case = Case(
        id="case",
        name="case",
        turns=(
            CaseTurn(
                id="turn",
                input={"email": "borrower@example.com"},
            ),
        ),
    )
    management = build_default_evaluator_management(
        judge_client=model_client,
        judge_model_id="judge-model",
        judge_credential_ref="env:AGENTGATE_JUDGE_API_KEY",
    )

    selected = management.select(("answer-quality",))
    judge_spec = selected[0]
    assert judge_spec.kind == EvaluatorKind.LLM_JUDGE
    assert judge_spec.config["model"] == {
        "provider_id": "company-llm",
        "model_id": "judge-model",
        "credential_ref": "env:AGENTGATE_JUDGE_API_KEY",
    }
    assert judge_spec.config["input_selection"] == "final_output"
    assert judge_spec.config["pass_threshold"] == 0.8
    assert judge_spec.config["temperature"] == 0
    management.validate_plan(
        DatasetVersion(dataset_id="dataset", cases=(case,)),
        selected,
    )
    result = management.evaluate_case(
        case,
        Trace(
            trace_id="0" * 32,
            run_id="run",
            case_id="case",
            spans=(),
            final_output={"answer": "authorization=top-secret"},
        ),
        selected,
    )[0]

    assert result.outcome == Outcome.PASS
    assert result.judge_record.provider_id == "company-llm"
    assert result.judge_record.requested_model == "judge-model"
    assert result.judge_record.resolved_model == "resolved-judge-model"
    assert result.judge_record.input_tokens == 12
    assert result.judge_record.output_tokens == 5
    assert len(sent_requests) == 1
    payload = json.loads(sent_requests[0].content)
    assert payload["model"] == "judge-model"
    rendered_request = sent_requests[0].content.decode()
    assert "borrower@example.com" not in rendered_request
    assert "top-secret" not in rendered_request
    assert "[redacted]" in rendered_request
    http_client.close()
