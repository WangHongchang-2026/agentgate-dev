import json
from itertools import combinations

import httpx
import pytest

from agentgate.application.evaluator_management import (
    BuiltinEvaluatorMutation,
    EvaluatorCatalogConflict,
    EvaluatorDraftNotFound,
    EvaluatorManagement,
    EvaluatorVersionNotFound,
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
    EvaluatorSeverity,
    EvaluatorSource,
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
from agentgate.storage.sqlite import SQLiteRepository


@pytest.fixture
def repository(tmp_path) -> SQLiteRepository:
    return SQLiteRepository(tmp_path / "evaluator-catalog.db")


@pytest.fixture
def default_management(repository: SQLiteRepository) -> EvaluatorManagement:
    return build_default_evaluator_management(repository)


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


def test_builtin_catalog_and_composition_are_exact(
    default_management: EvaluatorManagement,
) -> None:
    specs = default_management.default_specs

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
    identities = default_management.list_evaluators()
    assert all(item.source == EvaluatorSource.BUILTIN for item in identities)
    assert all(item.enabled for item in identities)
    assert all(item.created_at == item.updated_at for item in identities)


def test_default_builder_preserves_rule_only_catalog(
    repository: SQLiteRepository,
    default_management: EvaluatorManagement,
) -> None:
    management = build_default_evaluator_management(repository)

    assert management.default_specs == default_management.default_specs


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
    repository: SQLiteRepository,
) -> None:
    values = {
        "judge_client": object(),
        "judge_model_id": "judge-model",
        "judge_credential_ref": "env:AGENTGATE_JUDGE_API_KEY",
    }

    with pytest.raises(ValueError, match="must be provided together"):
        build_default_evaluator_management(
            repository,
            **{name: values[name] for name in provided},
        )


def test_constructor_copies_composition_and_rejects_misalignment(
    repository: SQLiteRepository,
) -> None:
    output_spec = spec("output", "final_output")
    implementations = {("final_output", "1"): FinalOutputEvaluator()}
    management = EvaluatorManagement(repository, (output_spec,), implementations)
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
        EvaluatorManagement(repository, (output_spec,), {})
    with pytest.raises(UnknownEvaluator, match="unknown evaluator implementation"):
        EvaluatorManagement(
            repository,
            (output_spec,),
            {("other", "1"): FinalOutputEvaluator()},
        )
    EvaluatorManagement(
        repository,
        (output_spec,),
        {
            ("final_output", "1"): FinalOutputEvaluator(),
            ("final_state", "1"): FinalStateEvaluator(),
        },
    )
    with pytest.raises(DuplicateEvaluatorId, match="unique"):
        EvaluatorManagement(repository, (output_spec, output_spec), {
            ("final_output", "1"): FinalOutputEvaluator(),
        })


def test_selection_preserves_order_and_rejects_invalid_requests(
    default_management: EvaluatorManagement,
) -> None:
    selected = default_management.select(
        ("final-output", "skill-routing")
    )

    assert tuple(item.id for item in selected) == (
        "final-output",
        "skill-routing",
    )
    assert default_management.select(None) is default_management.default_specs
    with pytest.raises(ValueError, match="at least one"):
        default_management.select(())
    with pytest.raises(DuplicateEvaluatorId, match="unique"):
        default_management.select(("final-output", "final-output"))
    with pytest.raises(UnknownEvaluator, match="unknown"):
        default_management.select(("unknown",))


def test_user_evaluator_lifecycle_publishes_and_selects_latest_version(
    default_management: EvaluatorManagement,
) -> None:
    evaluator, draft = default_management.create_evaluator(
        "Custom output",
        "Checks the final answer",
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="custom_output",
        implementation_id="final_output",
        config={},
    )

    assert evaluator.source == EvaluatorSource.USER
    assert evaluator.enabled is False
    assert draft.evaluator_id == evaluator.id
    assert evaluator not in default_management.list_evaluators()
    assert evaluator in default_management.list_evaluators(include_disabled=True)
    with pytest.raises(EvaluatorCatalogConflict, match="unpublished"):
        default_management.update_evaluator(evaluator.id, enabled=True)

    first = default_management.publish_draft(evaluator.id)
    assert first.id == evaluator.id
    assert first.version == "1"
    with pytest.raises(EvaluatorDraftNotFound, match="no active draft"):
        default_management.get_draft(evaluator.id)

    enabled = default_management.update_evaluator(evaluator.id, enabled=True)
    assert enabled.enabled is True
    assert default_management.select((evaluator.id,)) == (first,)

    cloned = default_management.create_draft(evaluator.id)
    assert cloned.based_on_version == "1"
    default_management.replace_draft(
        evaluator.id,
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="custom_output_v2",
        severity=EvaluatorSeverity.BLOCKING,
        implementation_id="final_output",
        implementation_version="1",
        config={},
        children=(),
        combination=None,
    )
    second = default_management.publish_draft(evaluator.id)

    assert second.version == "2"
    assert second.metric == "custom_output_v2"
    assert default_management.list_versions(evaluator.id) == (second, first)
    assert default_management.get_version(evaluator.id, "1") == first
    assert default_management.select((evaluator.id,)) == (second,)

    default_management.update_evaluator(evaluator.id, enabled=False)
    with pytest.raises(EvaluatorCatalogConflict, match="disabled"):
        default_management.select((evaluator.id,))
    assert default_management.validate_plan(
        DatasetVersion(dataset_id="historical"),
        (second,),
    ) is None
    with pytest.raises(EvaluatorCatalogConflict, match="cannot be deleted"):
        default_management.delete_evaluator(evaluator.id)


def test_unpublished_evaluator_draft_can_be_discarded_and_identity_deleted(
    default_management: EvaluatorManagement,
) -> None:
    evaluator, _ = default_management.create_evaluator(
        "Disposable",
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="disposable",
        implementation_id="final_output",
        config={},
    )

    default_management.discard_draft(evaluator.id)
    with pytest.raises(EvaluatorCatalogConflict, match="cannot clone"):
        default_management.create_draft(evaluator.id)
    default_management.delete_evaluator(evaluator.id)

    with pytest.raises(UnknownEvaluator, match="unknown Evaluator"):
        default_management.get_evaluator(evaluator.id)


def test_builtins_are_read_only_and_have_one_exact_version(
    default_management: EvaluatorManagement,
) -> None:
    builtin = default_management.get_evaluator("final-output")

    assert builtin.source == EvaluatorSource.BUILTIN
    assert default_management.list_versions(builtin.id) == (
        default_management.get_version(builtin.id, "1"),
    )
    with pytest.raises(BuiltinEvaluatorMutation, match="read-only"):
        default_management.update_evaluator(builtin.id, name="Changed")
    with pytest.raises(BuiltinEvaluatorMutation, match="read-only"):
        default_management.create_draft(builtin.id)
    with pytest.raises(EvaluatorVersionNotFound, match="@2"):
        default_management.get_version(builtin.id, "2")


def test_publish_rejects_rule_configuration_and_preserves_draft(
    default_management: EvaluatorManagement,
) -> None:
    evaluator, draft = default_management.create_evaluator(
        "Misconfigured rule",
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="misconfigured",
        implementation_id="final_output",
        config={"unsupported": True},
    )

    with pytest.raises(ValueError, match="config must be empty"):
        default_management.publish_draft(evaluator.id)

    assert default_management.get_draft(evaluator.id) == draft
    assert default_management.list_versions(evaluator.id) == ()


def test_stale_publication_is_reported_as_catalog_conflict(
    repository: SQLiteRepository,
    default_management: EvaluatorManagement,
    monkeypatch,
) -> None:
    evaluator, draft = default_management.create_evaluator(
        "Racing publication",
        kind=EvaluatorKind.RULE,
        dimension="answer",
        metric="racing_publication",
        implementation_id="final_output",
        config={},
    )

    def reject_stale_publication(expected_draft_id, published) -> None:
        del expected_draft_id, published
        raise ValueError("expected Evaluator draft does not exist")

    monkeypatch.setattr(
        repository,
        "publish_evaluator_draft",
        reject_stale_publication,
    )

    with pytest.raises(EvaluatorCatalogConflict, match="changed during publication"):
        default_management.publish_draft(evaluator.id)

    assert default_management.get_draft(evaluator.id) == draft


def test_publish_rejects_unavailable_judge_provider_without_model_call(
    repository: SQLiteRepository,
) -> None:
    http_client = httpx.Client(transport=httpx.MockTransport(lambda _: None))
    model_client = OpenAICompatibleModelClient(
        provider_id="configured-provider",
        base_url="https://models.example/v1",
        api_key="resolved-secret",
        http_client=http_client,
    )
    management = build_default_evaluator_management(
        repository,
        judge_client=model_client,
        judge_model_id="judge-model",
        judge_credential_ref="env:AGENTGATE_JUDGE_API_KEY",
    )
    evaluator, draft = management.create_evaluator(
        "Unavailable Judge",
        kind=EvaluatorKind.LLM_JUDGE,
        dimension="answer",
        metric="unavailable_judge",
        implementation_id="answer_quality",
        config={
            "model": {
                "provider_id": "missing-provider",
                "model_id": "judge-model",
                "credential_ref": "env:AGENTGATE_JUDGE_API_KEY",
            },
            "instruction": "Evaluate the answer.",
            "rubric": {"correctness": "The answer is correct."},
        },
    )

    with pytest.raises(ValueError, match="no Judge model client configured"):
        management.publish_draft(evaluator.id)

    assert management.get_draft(evaluator.id) == draft
    assert management.list_versions(evaluator.id) == ()
    http_client.close()


def test_validates_builtin_demo_and_rejects_catalog_drift(
    default_management: EvaluatorManagement,
) -> None:
    selected = default_management.default_specs

    assert default_management.validate_plan(
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
        default_management.validate_plan(
            LOAN_DATASET_VERSION,
            (drifted, *selected[1:]),
        )


def test_preflight_accepts_json_schema_and_rejects_unsupported_policies(
    default_management: EvaluatorManagement,
) -> None:
    state_specs = default_management.select(("final-state",))
    schema_dataset = draft_dataset(
        StateExpectation(
            path="value",
            condition=MatchesJsonSchema(json_schema={"type": "string"}),
        )
    )
    policy_dataset = draft_dataset(PolicyExpectation(policy_id="unknown_policy"))

    assert default_management.validate_plan(
        schema_dataset,
        state_specs,
    ) is None
    with pytest.raises(UnsupportedPolicy, match="unknown_policy"):
        default_management.validate_plan(policy_dataset, state_specs)


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
    default_management: EvaluatorManagement,
) -> None:
    dataset = draft_dataset(
        StateExpectation(
            path="value",
            condition=MatchesJsonSchema(json_schema=json_schema),
        )
    )
    state_specs = default_management.select(("final-state",))

    with pytest.raises(JsonSchemaConfigurationError, match=message):
        default_management.validate_plan(dataset, state_specs)


def test_preflight_rejects_metric_dimension_conflicts(
    repository: SQLiteRepository,
) -> None:
    first = spec("first", "final_state", dimension="state", metric="same")
    second = spec("second", "final_state", dimension="tool_use", metric="same")
    management = EvaluatorManagement(
        repository,
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


def test_preflight_rejects_missing_selected_dependencies(
    repository: SQLiteRepository,
) -> None:
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
        repository,
        (hybrid,),
        {("hybrid", "1"): HybridImplementation()},
    )

    with pytest.raises(MissingEvaluatorDependency, match="rule"):
        management.validate_plan(DatasetVersion(dataset_id="dataset"), (hybrid,))


def test_composes_and_executes_judge_through_application_boundary(
    repository: SQLiteRepository,
) -> None:
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
        repository,
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
