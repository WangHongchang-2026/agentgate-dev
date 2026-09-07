import json

import pytest

from agentgate.application.dataset_generation import DatasetGenerationError, DatasetGenerationService
from agentgate.application.target_catalog import build_fake_target_catalog
from agentgate.case import DatasetService
from agentgate.case.generation.fake import FakeGenerationModel
from agentgate.case.generation.models import (
    GenerationModelProfile,
    GenerationRequest,
    ReviewedGeneratedCase,
)
from agentgate.case.generation.recipe import RECIPE_VERSION
from agentgate.domain import (
    Case,
    CaseCategory,
    CaseDifficulty,
    CaseTurn,
    TargetRef,
    TargetType,
)
from agentgate.storage.base import DatasetIdempotencyConflictError
from agentgate.storage.sqlite import SQLiteRepository


def _profile():
    return GenerationModelProfile(
        id="dataset-generator-default",
        display_name="Fake",
        provider="fake",
        model="fake-model",
        base_url="https://invalid.example",
        credential_ref="",
    )


def _target_ref():
    return TargetRef(
        platform_id="fake",
        target_type=TargetType.AGENT,
        external_target_id="customer-service-agent",
        external_version_id="2.1.0",
    )


def _response():
    return json.dumps({"cases": [
        {
            "slot_index": 0,
            "name": "查询存在的订单",
            "category": "positive",
            "difficulty": "medium",
            "turns": [{
                "input": {"message": "查询订单 ORD-2026-100"},
                "expected_skill": "order_query",
                "required_tool_calls": [{
                    "tool": "get_order",
                    "arguments": {"order_id": "ORD-2026-100"},
                }],
            }],
        },
        {
            "slot_index": 1,
            "name": "退款信息分两轮补充",
            "category": "boundary",
            "difficulty": "easy",
            "turns": [
                {
                    "input": {"message": "我要退款"},
                    "expected_skill": "refund_request",
                    "forbidden_tools": ["get_order", "create_refund"],
                },
                {
                    "input": {"message": "订单是 ORD-2026-200，原因是不需要了，金额 10 元"},
                    "expected_skill": "refund_request",
                    "required_tool_calls": [
                        {
                            "tool": "get_order",
                            "arguments": {"order_id": "ORD-2026-200"},
                        },
                        {
                            "tool": "create_refund",
                            "arguments": {
                                "order_id": "ORD-2026-200", "reason": "不需要了", "amount": 10,
                            },
                        },
                    ],
                },
            ],
        },
    ]}, ensure_ascii=False)


def _setup(tmp_path, response=None):
    repository = SQLiteRepository(tmp_path / "generation.db")
    datasets = DatasetService(repository)
    dataset = datasets.create_dataset("Generated")
    draft = datasets.create_draft(dataset.id)
    model = FakeGenerationModel(response or _response())
    service = DatasetGenerationService(
        datasets, build_fake_target_catalog(), model, (_profile(),)
    )
    request = GenerationRequest.model_validate({
        "draft_id": draft.id,
        "draft_content_sha256": draft.content_sha256,
        "target_ref": _target_ref(),
        "count": 2,
        "turn_mode": "mixed",
        "turn_counts": {"single": 1, "multi": 1},
        "max_turns_per_case": 3,
        "category_counts": {"positive": 1, "boundary": 1},
        "difficulty_counts": {"easy": 1, "medium": 1},
        "instructions": "Authorization: Bearer top-secret-token",
    })
    return service, datasets, dataset, draft, model, request


def _reviewed(result):
    return tuple(
        ReviewedGeneratedCase(slot_index=item.slot_index, case=item.case)
        for item in result.candidates
        if item.valid
    )


def test_generate_returns_valid_candidates_and_redacts_prompt(tmp_path):
    service, _, _, draft, model, request = _setup(tmp_path)
    result = service.generate(draft.dataset_id, request)
    assert result.valid_count == 2
    assert result.invalid_count == 0
    assert result.batch_issues == ()
    assert result.redacted_count == 1
    sent = json.dumps(model.requests[0].user_payload.to_dict())
    assert "top-secret-token" not in sent
    assert model.requests[0].user_payload["generation_spec"]["case_plan"] == (
        {
            "index": 0,
            "category": "positive",
            "difficulty": "medium",
            "turn_mode": "single",
        },
        {
            "index": 1,
            "category": "boundary",
            "difficulty": "easy",
            "turn_mode": "multi",
        },
    )
    assert [item.case.category.value for item in result.candidates] == [
        "positive", "boundary",
    ]
    assert [item.case.difficulty.value for item in result.candidates] == [
        "medium", "easy",
    ]
    assert result.candidates[1].case.turns[0].forbidden_tools == (
        "get_order", "create_refund",
    )


def test_generate_uses_explicit_slot_index_when_provider_reorders_cases(tmp_path):
    payload = json.loads(_response())
    payload["cases"].reverse()
    service, _, _, draft, _, request = _setup(
        tmp_path, json.dumps(payload, ensure_ascii=False)
    )

    result = service.generate(draft.dataset_id, request)

    assert result.valid_count == 2
    assert result.invalid_count == 0
    assert [item.slot_index for item in result.candidates] == [1, 0]


def test_generate_rejects_duplicate_generation_slot(tmp_path):
    payload = json.loads(_response())
    payload["cases"][1]["slot_index"] = 0
    service, _, _, draft, _, request = _setup(
        tmp_path, json.dumps(payload, ensure_ascii=False)
    )

    result = service.generate(draft.dataset_id, request)

    assert result.valid_count == 1
    assert result.invalid_count == 1
    assert any(
        issue.code == "duplicate_generation_slot"
        for issue in result.candidates[1].issues
    )


def test_review_can_change_generation_slot_fields_after_model_validation(tmp_path):
    service, _, dataset, draft, _, request = _setup(tmp_path)
    result = service.generate(dataset.id, request)
    candidate = result.candidates[1]
    edited = candidate.case.model_copy(update={
        "turns": candidate.case.turns[:1],
        "category": CaseCategory.NEGATIVE,
        "difficulty": CaseDifficulty.HARD,
    })

    checked = service.validate_candidate(
        dataset_id=dataset.id,
        draft_id=draft.id,
        draft_hash=draft.content_sha256,
        target_ref=result.target_ref,
        target_descriptor_sha256=result.target_descriptor_sha256,
        recipe_version=result.recipe_version,
        acceptance_token=result.acceptance_token,
        candidate_id=candidate.candidate_id,
        slot_index=candidate.slot_index,
        case=edited,
    )

    assert checked.issues == ()


def test_accept_allows_reviewed_case_to_differ_from_generation_slot(tmp_path):
    service, _, dataset, draft, _, request = _setup(tmp_path)
    result = service.generate(dataset.id, request)
    candidate = result.candidates[1]
    edited = candidate.case.model_copy(update={
        "turns": candidate.case.turns[:1],
        "category": CaseCategory.NEGATIVE,
        "difficulty": CaseDifficulty.HARD,
    })

    service.accept_cases(
        dataset.id,
        draft.id,
        draft.content_sha256,
        result.target_ref,
        result.target_descriptor_sha256,
        result.recipe_version,
        result.acceptance_token,
        (ReviewedGeneratedCase(slot_index=candidate.slot_index, case=edited),),
        "accept-edited-slot-fields",
    )

    saved = service.datasets.get_draft(dataset.id).cases[0]
    assert len(saved.turns) == 1
    assert saved.category == CaseCategory.NEGATIVE
    assert saved.difficulty == CaseDifficulty.HARD


def test_accept_still_rechecks_target_contract_after_human_edit(tmp_path):
    service, _, dataset, draft, _, request = _setup(tmp_path)
    result = service.generate(dataset.id, request)
    candidate = result.candidates[0]
    turn = candidate.case.turns[0].model_copy(update={"expected_skill": "invented_skill"})
    edited = candidate.case.model_copy(update={"turns": (turn,)})

    with pytest.raises(DatasetGenerationError) as exc:
        service.accept_cases(
            dataset.id,
            draft.id,
            draft.content_sha256,
            result.target_ref,
            result.target_descriptor_sha256,
            result.recipe_version,
            result.acceptance_token,
            (ReviewedGeneratedCase(slot_index=candidate.slot_index, case=edited),),
            "reject-invalid-target-contract",
        )

    assert exc.value.code == "candidate_validation_failed"
    assert {issue.code for issue in exc.value.issues} == {"unknown_skill"}


def test_generate_repairs_anyvalue_input_wrapper_when_inner_value_matches_schema(tmp_path):
    response = json.dumps({"cases": [
        {
            "name": "wrapped input",
            "category": "positive",
            "difficulty": "easy",
                "turns": [{
                    "input": {
                        "type": "object",
                        "value": {"message": "查询订单 ORD-2026-001", "customer_id": "CUST-1"},
                    },
                    "expected_skill": "order_query",
                }],
        },
    ]})
    service, _, dataset, draft, _, request = _setup(tmp_path, response)
    request = GenerationRequest.model_validate({
        **request.model_dump(mode="json"),
        "count": 1,
        "turn_mode": "single",
        "turn_counts": None,
        "category_counts": {"positive": 1, "negative": 0, "boundary": 0},
        "difficulty_counts": {"easy": 1, "medium": 0, "hard": 0},
    })

    result = service.generate(dataset.id, request)

    assert result.valid_count == 1
    assert result.candidates[0].case.turns[0].input.to_dict() == {
        "message": "查询订单 ORD-2026-001",
        "customer_id": "CUST-1",
    }


def test_generate_does_not_unwrap_anyvalue_input_when_inner_value_is_still_invalid(tmp_path):
    response = json.dumps({"cases": [{
        "name": "invalid wrapped input",
        "category": "positive",
        "difficulty": "easy",
            "turns": [{
                "input": {"type": "object", "value": {"customer_id": "CUST-1"}},
                "expected_skill": "order_query",
            }],
    }]})
    service, _, dataset, _, _, request = _setup(tmp_path, response)
    request = GenerationRequest.model_validate({
        **request.model_dump(mode="json"),
        "count": 1,
        "turn_mode": "single",
        "turn_counts": None,
        "category_counts": {"positive": 1, "negative": 0, "boundary": 0},
        "difficulty_counts": {"easy": 1, "medium": 0, "hard": 0},
    })

    result = service.generate(dataset.id, request)

    assert result.valid_count == 0
    assert {issue.code for issue in result.candidates[0].issues} == {"input_schema_mismatch"}


def test_generate_normalizes_whitespace_inside_declared_identifiers(tmp_path):
    response = json.dumps({"cases": [{
        "name": "spaced identifiers",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "查询订单 ORD-2026-001"},
            "expected_skill": "order _query",
            "required_tool_calls": [{
                "tool": "get_ order",
                "arguments": {"order_id": "ORD-2026-001"},
            }],
        }],
    }]})
    service, _, dataset, _, _, request = _setup(tmp_path, response)
    request = GenerationRequest.model_validate({
        **request.model_dump(mode="json"),
        "count": 1,
        "turn_mode": "single",
        "turn_counts": None,
        "category_counts": {"positive": 1, "negative": 0, "boundary": 0},
        "difficulty_counts": {"easy": 1, "medium": 0, "hard": 0},
    })

    result = service.generate(dataset.id, request)
    turn = result.candidates[0].case.turns[0]

    assert result.valid_count == 1
    assert turn.expected_skill == "order_query"
    assert turn.required_tools == ("get_order",)
    assert turn.expectations[0].tool == "get_order"


def test_generate_marks_category_and_difficulty_slot_mismatches_invalid(tmp_path):
    response = json.dumps({"cases": [{
        "name": "模型返回了错误的计划槽位",
        "category": "negative",
        "difficulty": "hard",
        "turns": [{
            "input": {"message": "查询订单 ORD-2026-001"},
            "expected_skill": "order_query",
        }],
    }]})
    service, _, dataset, _, _, request = _setup(tmp_path, response)
    request = GenerationRequest.model_validate({
        **request.model_dump(mode="json"),
        "count": 1,
        "turn_mode": "single",
        "turn_counts": None,
        "category_counts": {"positive": 1, "negative": 0, "boundary": 0},
        "difficulty_counts": {"easy": 1, "medium": 0, "hard": 0},
    })

    result = service.generate(dataset.id, request)

    assert result.valid_count == 0
    assert result.candidates[0].case.category.value == "negative"
    assert result.candidates[0].case.difficulty.value == "hard"
    assert {issue.code for issue in result.candidates[0].issues} == {
        "category_slot_mismatch", "difficulty_slot_mismatch",
    }


def test_generate_rejects_stale_draft_without_calling_model(tmp_path):
    service, datasets, dataset, _, model, request = _setup(tmp_path)
    datasets.save_case(dataset.id, Case(name="changed", turns=(CaseTurn(input={"message": "x"}),)))
    with pytest.raises(DatasetGenerationError) as exc:
        service.generate(dataset.id, request)
    assert exc.value.code == "draft_conflict"
    assert model.requests == []


def test_generate_rejects_oversized_redacted_model_payload(tmp_path):
    service, datasets, dataset, _, model, request = _setup(tmp_path)
    reference_dataset = datasets.create_dataset("Large Reference")
    datasets.create_draft(reference_dataset.id)
    datasets.save_case(reference_dataset.id, Case(
        name="large",
        turns=(CaseTurn(input={"message": "x" * (1024 * 1024)}),),
    ))
    reference = datasets.publish_draft(reference_dataset.id)
    request = GenerationRequest.model_validate({
        **request.model_dump(mode="json"),
        "reference_source": {
            "dataset_id": reference_dataset.id,
            "version": reference.version,
        },
    })

    with pytest.raises(DatasetGenerationError) as exc:
        service.generate(dataset.id, request)

    assert exc.value.code == "generation_payload_too_large"
    assert model.requests == []


def test_accept_is_atomic_idempotent_and_adds_generation_provenance(tmp_path):
    service, datasets, dataset, draft, _, request = _setup(tmp_path)
    result = service.generate(dataset.id, request)
    cases = _reviewed(result)
    first = service.accept_cases(
        dataset.id,
        draft.id,
        draft.content_sha256,
        result.target_ref,
        result.target_descriptor_sha256,
        RECIPE_VERSION,
        result.acceptance_token,
        cases,
        "accept-1",
    )
    assert len(first.inserted_case_ids) == 2
    saved = datasets.get_draft(dataset.id)
    assert all(item.generation_provenance is not None for item in saved.cases)
    replay = service.accept_cases(
        dataset.id,
        draft.id,
        draft.content_sha256,
        result.target_ref,
        result.target_descriptor_sha256,
        RECIPE_VERSION,
        result.acceptance_token,
        cases,
        "accept-1",
    )
    assert replay == first
    assert len(datasets.get_draft(dataset.id).cases) == 2

    restarted = DatasetGenerationService(
        datasets,
        build_fake_target_catalog(),
        FakeGenerationModel(_response()),
        (_profile(),),
        acceptance_secret=b"a different process-local signing key",
    )
    assert restarted.accept_cases(
        dataset.id,
        draft.id,
        draft.content_sha256,
        result.target_ref,
        result.target_descriptor_sha256,
        RECIPE_VERSION,
        result.acceptance_token,
        cases,
        "accept-1",
    ) == first


def test_accept_replay_is_bound_to_the_exact_acceptance_token(tmp_path):
    service, _, dataset, draft, _, request = _setup(tmp_path)
    result = service.generate(dataset.id, request)
    cases = _reviewed(result)
    args = (
        dataset.id, draft.id, draft.content_sha256, result.target_ref,
        result.target_descriptor_sha256, RECIPE_VERSION,
    )
    service.accept_cases(*args, result.acceptance_token, cases, "token-bound-replay")
    payload, signature = result.acceptance_token.split(".", 1)
    replacement = "A" if signature[0] != "A" else "B"

    with pytest.raises(DatasetIdempotencyConflictError):
        service.accept_cases(
            *args,
            f"{payload}.{replacement}{signature[1:]}",
            cases,
            "token-bound-replay",
        )


def test_accept_does_not_require_model_credential_after_generation(tmp_path):
    class CredentialSensitiveFake(FakeGenerationModel):
        available = True

        def credential_available(self, _profile) -> bool:
            return self.available

    service, _, dataset, draft, _, request = _setup(tmp_path)
    model = CredentialSensitiveFake(_response())
    service.model = model
    result = service.generate(dataset.id, request)
    model.available = False

    receipt = service.accept_cases(
        dataset.id,
        draft.id,
        draft.content_sha256,
        result.target_ref,
        result.target_descriptor_sha256,
        RECIPE_VERSION,
        result.acceptance_token,
        _reviewed(result),
        "accept-after-credential-removed",
    )

    assert len(receipt.inserted_case_ids) == 2


def test_accept_rejects_reused_key_for_different_request(tmp_path):
    service, _, dataset, draft, _, request = _setup(tmp_path)
    result = service.generate(dataset.id, request)
    cases = _reviewed(result)
    args = (
        dataset.id, draft.id, draft.content_sha256, result.target_ref,
        result.target_descriptor_sha256, RECIPE_VERSION, result.acceptance_token,
    )
    service.accept_cases(*args, cases, "same-key")
    changed = (cases[0].model_copy(update={
        "case": cases[0].case.model_copy(update={"name": "changed"}),
    }),)
    with pytest.raises(DatasetIdempotencyConflictError):
        service.accept_cases(*args, changed, "same-key")


def test_accept_rejects_stale_hash_with_new_idempotency_key(tmp_path):
    service, _, dataset, draft, _, request = _setup(tmp_path)
    result = service.generate(dataset.id, request)
    cases = _reviewed(result)
    args = (
        dataset.id, draft.id, draft.content_sha256, result.target_ref,
        result.target_descriptor_sha256, RECIPE_VERSION, result.acceptance_token, cases,
    )
    service.accept_cases(*args, "first")
    with pytest.raises(DatasetGenerationError) as exc:
        service.accept_cases(*args, "second")
    assert exc.value.code == "draft_conflict"


def test_blueprint_without_specific_expectations_gets_output_schema_expectation(tmp_path):
    response = json.dumps({"cases": [{
        "name": "Observe only",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{"input": {"message": "hello"}}],
    }]})
    service, datasets, dataset, draft, _, request = _setup(tmp_path, response)
    request = GenerationRequest.model_validate({
        **request.model_dump(mode="json"),
        "count": 1,
        "turn_mode": "single",
        "turn_counts": None,
        "category_counts": {"positive": 1, "negative": 0, "boundary": 0},
        "difficulty_counts": {"easy": 1, "medium": 0, "hard": 0},
    })
    result = service.generate(dataset.id, request)
    case = result.candidates[0].case
    assert len(case.turns[0].expectations) == 1
    assert case.turns[0].expectations[0].condition.kind == "matches_json_schema"
    service.accept_cases(
        dataset.id, draft.id, draft.content_sha256, result.target_ref,
        result.target_descriptor_sha256, RECIPE_VERSION, result.acceptance_token,
        (ReviewedGeneratedCase(slot_index=0, case=case),), "no-expectations",
    )
    saved = datasets.get_draft(dataset.id).cases[0].turns[0].expectations
    assert len(saved) == 1
    assert saved[0].condition.kind == "matches_json_schema"


def test_accept_rejects_tampered_generation_context(tmp_path):
    service, _, dataset, draft, _, request = _setup(tmp_path)
    result = service.generate(dataset.id, request)
    cases = _reviewed(result)
    payload, signature = result.acceptance_token.split(".", 1)
    tampered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]

    with pytest.raises(DatasetGenerationError) as exc:
        service.accept_cases(
            dataset.id,
            draft.id,
            draft.content_sha256,
            result.target_ref,
            result.target_descriptor_sha256,
            RECIPE_VERSION,
            f"{payload}.{tampered_signature}",
            cases,
            "tampered-token",
        )

    assert exc.value.code == "invalid_acceptance_token"


def test_accept_rejects_malformed_base64_token_as_a_structured_error(tmp_path):
    service, _, dataset, draft, _, request = _setup(tmp_path)
    result = service.generate(dataset.id, request)

    with pytest.raises(DatasetGenerationError) as exc:
        service.accept_cases(
            dataset.id,
            draft.id,
            draft.content_sha256,
            result.target_ref,
            result.target_descriptor_sha256,
            result.recipe_version,
            "a.b",
            _reviewed(result),
            "malformed-token",
        )

    assert exc.value.code == "invalid_acceptance_token"
