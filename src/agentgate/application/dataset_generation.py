"""Application use case for generating, reviewing, and accepting candidate Cases."""

from __future__ import annotations

import base64
from collections import defaultdict, deque
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Iterable

from agentgate.application.target_catalog import TargetCatalog
from agentgate.case.generation.blueprint import parse_blueprint_response
from agentgate.case.generation.dedup import case_functional_fingerprint
from agentgate.case.generation.models import (
    CandidateIssue,
    GeneratedCandidate,
    GenerationModelProfile,
    GenerationRequest,
    GenerationResult,
    GenerationSlot,
    ReviewedGeneratedCase,
    TurnMode,
)
from agentgate.case.generation.policy import instruction_issues, validate_case_for_target
from agentgate.case.generation.protocol import GenerationModel
from agentgate.case.generation.recipe import (
    RECIPE_VERSION,
    build_generation_slots,
    build_model_request,
)
from agentgate.case.service import DatasetService
from agentgate.domain import (
    Case,
    FrozenJsonObject,
    GeneratedCaseProvenance,
    TargetRef,
    ToolArgumentExpectation,
    canonical_json,
    content_sha256,
)
from agentgate.storage.base import DatasetMutationReceipt
from agentgate.trace.redaction import redact

MAX_MODEL_PAYLOAD_BYTES = 1024 * 1024
ACCEPTANCE_TOKEN_TTL_SECONDS = 2 * 60 * 60


class DatasetGenerationError(ValueError):
    def __init__(self, code: str, message: str, issues: tuple[CandidateIssue, ...] = ()) -> None:
        self.code = code
        self.issues = issues
        super().__init__(message)


def _prefix_issues(prefix: str, issues: Iterable[CandidateIssue]) -> tuple[CandidateIssue, ...]:
    return tuple(CandidateIssue(
        path=f"{prefix}.{item.path}" if item.path else prefix,
        code=item.code,
        message=item.message,
    ) for item in issues)


def _select_references(cases: tuple[Case, ...], count: int = 20) -> tuple[Case, ...]:
    groups: dict[tuple[str, str], deque[Case]] = defaultdict(deque)
    for case in sorted(cases, key=lambda item: item.id):
        groups[(case.category.value, case.difficulty.value)].append(case)
    selected: list[Case] = []
    keys = sorted(groups)
    while len(selected) < count and any(groups.values()):
        for key in keys:
            if groups[key] and len(selected) < count:
                selected.append(groups[key].popleft())
    return tuple(selected)


def _normalize_anyvalue_input_envelopes(case: Case, descriptor) -> Case:
    """Repair a model wrapper only when its inner value matches the Target schema."""
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(descriptor.input_schema.to_dict())
    changed = False
    turns = []
    for turn in case.turns:
        value = turn.input.to_dict()
        inner = value.get("value")
        should_unwrap = (
            set(value) == {"type", "value"}
            and value.get("type") == "object"
            and isinstance(inner, dict)
            and not validator.is_valid(value)
            and validator.is_valid(inner)
        )
        if should_unwrap:
            turn = turn.model_copy(update={"input": FrozenJsonObject(inner)})
            changed = True
        turns.append(turn)
    return case.model_copy(update={"turns": tuple(turns)}) if changed else case


def _resolve_declared_identifier(value: str, allowed: tuple[str, ...]) -> str:
    stripped = value.strip()
    if stripped in allowed:
        return stripped
    compact = re.sub(r"\s+", "", stripped)
    matches = [item for item in allowed if re.sub(r"\s+", "", item) == compact]
    return matches[0] if len(matches) == 1 else stripped


def _normalize_declared_identifiers(case: Case, descriptor) -> Case:
    skill_names = tuple(item.name for item in descriptor.skills)
    tool_names = tuple(item.name for item in descriptor.tools)
    changed = False
    turns = []
    for turn in case.turns:
        expected_skill = turn.expected_skill
        if expected_skill is not None:
            normalized_skill = _resolve_declared_identifier(expected_skill, skill_names)
            changed = changed or normalized_skill != expected_skill
            expected_skill = normalized_skill
        required_tools = tuple(dict.fromkeys(
            _resolve_declared_identifier(item, tool_names) for item in turn.required_tools
        ))
        forbidden_tools = tuple(dict.fromkeys(
            _resolve_declared_identifier(item, tool_names) for item in turn.forbidden_tools
        ))
        changed = changed or required_tools != turn.required_tools
        changed = changed or forbidden_tools != turn.forbidden_tools
        expectations = []
        for expectation in turn.expectations:
            if isinstance(expectation, ToolArgumentExpectation):
                normalized_tool = _resolve_declared_identifier(expectation.tool, tool_names)
                if normalized_tool != expectation.tool:
                    expectation = expectation.model_copy(update={"tool": normalized_tool})
                    changed = True
            expectations.append(expectation)
        turns.append(turn.model_copy(update={
            "expected_skill": expected_skill,
            "required_tools": required_tools,
            "forbidden_tools": forbidden_tools,
            "expectations": tuple(expectations),
        }))
    return case.model_copy(update={"turns": tuple(turns)}) if changed else case


class DatasetGenerationService:
    def __init__(
        self,
        datasets: DatasetService,
        targets: TargetCatalog,
        model: GenerationModel,
        profiles: tuple[GenerationModelProfile, ...],
        acceptance_secret: bytes | None = None,
    ) -> None:
        self.datasets = datasets
        self.targets = targets
        self.model = model
        self._profiles = {item.id: item for item in profiles}
        if acceptance_secret is None:
            secret_loader = getattr(datasets.repository, "get_or_create_service_secret", None)
            acceptance_secret = (
                secret_loader("dataset_generation_acceptance_hmac")
                if secret_loader is not None
                else secrets.token_bytes(32)
            )
        self._acceptance_secret = acceptance_secret

    def _issue_acceptance_token(
        self,
        draft_id: str,
        draft_hash: str,
        target_ref: TargetRef,
        descriptor_hash: str,
        profile_id: str,
        slots: tuple[GenerationSlot, ...],
        max_turns_per_case: int,
    ) -> str:
        payload = canonical_json({
            "version": 2,
            "draft_id": draft_id,
            "draft_hash": draft_hash,
            "target_ref": target_ref.model_dump(mode="json"),
            "descriptor_hash": descriptor_hash,
            "recipe_version": RECIPE_VERSION,
            "model_profile_id": profile_id,
            "slots": [item.model_dump(mode="json") for item in slots],
            "max_turns_per_case": max_turns_per_case,
            "issued_at": int(time.time()),
        }).encode("utf-8")
        signature = hmac.new(self._acceptance_secret, payload, hashlib.sha256).digest()
        return ".".join(
            base64.urlsafe_b64encode(part).decode("ascii").rstrip("=")
            for part in (payload, signature)
        )

    def _verify_acceptance_token(
        self,
        token: str,
        draft_id: str,
        draft_hash: str,
        target_ref: TargetRef,
        descriptor_hash: str,
        recipe_version: str,
    ) -> tuple[str, int, tuple[GenerationSlot, ...], int]:
        try:
            payload_text, signature_text = token.split(".", 1)
            payload = base64.urlsafe_b64decode(payload_text + "=" * (-len(payload_text) % 4))
            signature = base64.urlsafe_b64decode(
                signature_text + "=" * (-len(signature_text) % 4)
            )
            expected_signature = hmac.new(
                self._acceptance_secret, payload, hashlib.sha256
            ).digest()
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("signature mismatch")
            context = json.loads(payload)
            expected = {
                "version": 2,
                "draft_id": draft_id,
                "draft_hash": draft_hash,
                "target_ref": target_ref.model_dump(mode="json"),
                "descriptor_hash": descriptor_hash,
                "recipe_version": recipe_version,
            }
            if any(context.get(key) != value for key, value in expected.items()):
                raise ValueError("context mismatch")
            profile_id = context["model_profile_id"]
            issued_at = context["issued_at"]
            max_turns_per_case = context["max_turns_per_case"]
            raw_slots = context["slots"]
            if (
                not isinstance(profile_id, str)
                or not isinstance(issued_at, int)
                or not isinstance(max_turns_per_case, int)
                or not isinstance(raw_slots, list)
            ):
                raise ValueError("invalid token fields")
            slots = tuple(GenerationSlot.model_validate(item) for item in raw_slots)
            if not slots or len(slots) > 20 or max_turns_per_case < 2 or max_turns_per_case > 5:
                raise ValueError("invalid generation contract")
            if [item.index for item in slots] != list(range(len(slots))):
                raise ValueError("invalid generation slots")
            return profile_id, issued_at, slots, max_turns_per_case
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise DatasetGenerationError(
                "invalid_acceptance_token", "生成接收令牌无效，请重新生成候选"
            ) from exc

    @staticmethod
    def _acceptance_profile_id(token: str) -> str:
        """Read only the profile needed to locate an existing idempotency receipt."""
        try:
            payload_text = token.split(".", 1)[0]
            payload = base64.urlsafe_b64decode(payload_text + "=" * (-len(payload_text) % 4))
            profile_id = json.loads(payload)["model_profile_id"]
            if not isinstance(profile_id, str):
                raise ValueError("invalid profile")
            return profile_id
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            raise DatasetGenerationError(
                "invalid_acceptance_token", "生成接收令牌无效，请重新生成候选"
            ) from exc

    def list_model_profiles(self) -> tuple[dict, ...]:
        availability = getattr(self.model, "credential_available", lambda _profile: True)
        return tuple(
            profile.public_dict(bool(availability(profile)))
            for profile in sorted(self._profiles.values(), key=lambda item: item.id)
        )

    def model_profile(self, profile_id: str) -> GenerationModelProfile:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise DatasetGenerationError("unknown_model_profile", "未知的模型配置")
        return profile

    def _profile(self, profile_id: str) -> GenerationModelProfile:
        profile = self.model_profile(profile_id)
        availability = getattr(self.model, "credential_available", lambda _profile: True)
        if not availability(profile):
            raise DatasetGenerationError(
                "provider_credential_unavailable", "模型凭据尚未配置"
            )
        return profile

    def _draft(self, dataset_id: str, draft_id: str, draft_hash: str):
        draft = self.datasets.get_draft(dataset_id)
        if draft is None:
            raise DatasetGenerationError("draft_not_found", "测评集没有活动草稿")
        if draft.id != draft_id or draft.content_sha256 != draft_hash:
            raise DatasetGenerationError("draft_conflict", "草稿已变化，请刷新后重试")
        return draft

    def _references(self, request: GenerationRequest) -> tuple[Case, ...]:
        if request.reference_source is None:
            return ()
        version = self.datasets.get_version(
            request.reference_source.dataset_id, request.reference_source.version
        )
        if request.reference_case_ids:
            by_id = {item.id: item for item in version.cases}
            unknown = [item for item in request.reference_case_ids if item not in by_id]
            if unknown:
                raise DatasetGenerationError(
                    "unknown_reference_case",
                    f"参考版本中不存在 Case：{', '.join(unknown)}",
                )
            return tuple(by_id[item] for item in request.reference_case_ids)
        return _select_references(version.cases)

    def generate(self, dataset_id: str, request: GenerationRequest) -> GenerationResult:
        draft = self._draft(dataset_id, request.draft_id, request.draft_content_sha256)
        policy_issues = instruction_issues(request.instructions)
        if policy_issues:
            raise DatasetGenerationError("forbidden_generation_topic", "生成主题不允许", policy_issues)
        descriptor = self.targets.resolve(request.target_ref)
        profile = self._profile(request.model_profile_id)
        references = self._references(request)
        model_request = build_model_request(request, descriptor, references, profile)
        redacted = redact(model_request.user_payload)
        redacted_count = redacted.redacted_count
        if len(canonical_json(redacted.value).encode("utf-8")) > MAX_MODEL_PAYLOAD_BYTES:
            raise DatasetGenerationError(
                "generation_payload_too_large",
                "脱敏后的 Target、配置和参考用例超过 1 MiB 大小限制",
            )
        model_request = model_request.model_copy(update={
            "user_payload": FrozenJsonObject(redacted.value),
        })
        response = self.model.generate(model_request)
        candidates, generated_count, batch_issues = parse_blueprint_response(
            response.content, descriptor
        )
        slots = build_generation_slots(request)
        draft_fingerprints = {case_functional_fingerprint(item) for item in draft.cases}
        batch_fingerprints: set[str] = set()
        seen_slot_indexes: set[int] = set()
        checked = []
        for candidate_index, candidate in enumerate(candidates):
            if candidate.case is None:
                checked.append(candidate)
                continue
            slot_index = (
                candidate.slot_index
                if candidate.slot_index is not None
                else candidate_index
            )
            if slot_index >= len(slots):
                checked.append(candidate.model_copy(update={"issues": (
                    CandidateIssue(
                        path="slot_index",
                        code="unexpected_generation_slot",
                        message=f"模型返回了生成计划之外的槽位：{slot_index}",
                    ),
                )}))
                continue
            if slot_index in seen_slot_indexes:
                checked.append(candidate.model_copy(update={"issues": (
                    CandidateIssue(
                        path="slot_index",
                        code="duplicate_generation_slot",
                        message=f"模型重复返回生成槽位：{slot_index}",
                    ),
                )}))
                continue
            seen_slot_indexes.add(slot_index)
            slot = slots[slot_index]
            normalized_case = _normalize_anyvalue_input_envelopes(candidate.case, descriptor)
            normalized_case = _normalize_declared_identifiers(normalized_case, descriptor)
            candidate = candidate.model_copy(update={
                "slot_index": slot_index,
                "case": normalized_case,
            })
            issues = list(candidate.issues)
            if candidate.case.category != slot.category:
                issues.append(CandidateIssue(
                    path="category",
                    code="category_slot_mismatch",
                    message=(
                        f"槽位 {slot_index} 应为 {slot.category.value}，"
                        f"模型返回 {candidate.case.category.value}"
                    ),
                ))
            if candidate.case.difficulty != slot.difficulty:
                issues.append(CandidateIssue(
                    path="difficulty",
                    code="difficulty_slot_mismatch",
                    message=(
                        f"槽位 {slot_index} 应为 {slot.difficulty.value}，"
                        f"模型返回 {candidate.case.difficulty.value}"
                    ),
                ))
            issues.extend(validate_case_for_target(
                candidate.case,
                descriptor,
                TurnMode(slot.turn_mode),
                request.max_turns_per_case,
            ))
            generated_policy = instruction_issues(canonical_json(candidate.case))
            issues.extend(CandidateIssue(
                path="case",
                code=item.code,
                message=item.message,
            ) for item in generated_policy)
            fingerprint = case_functional_fingerprint(candidate.case)
            if fingerprint in draft_fingerprints or fingerprint in batch_fingerprints:
                issues.append(CandidateIssue(
                    path="case",
                    code="duplicate_case",
                    message="候选与当前草稿或本批其他用例功能重复",
                ))
            else:
                batch_fingerprints.add(fingerprint)
            checked.append(candidate.model_copy(update={"issues": tuple(issues)}))
        batch_issues = batch_issues + self._quota_issues(request, tuple(checked), generated_count)
        valid_count = sum(item.valid for item in checked)
        acceptance_token = self._issue_acceptance_token(
            draft.id,
            draft.content_sha256,
            descriptor.ref,
            descriptor.descriptor_sha256,
            profile.id,
            slots,
            request.max_turns_per_case,
        )
        return GenerationResult(
            requested_count=request.count,
            generated_count=generated_count,
            valid_count=valid_count,
            invalid_count=len(checked) - valid_count,
            candidates=tuple(checked),
            batch_issues=batch_issues,
            target_ref=descriptor.ref,
            target_descriptor_sha256=descriptor.descriptor_sha256,
            recipe_version=RECIPE_VERSION,
            provider=profile.provider,
            model_profile_id=profile.id,
            requested_model=profile.model,
            response_model=response.response_model,
            provider_request_id=response.request_id,
            acceptance_token=acceptance_token,
            redacted_count=redacted_count,
            draft_id=draft.id,
            draft_content_sha256=draft.content_sha256,
        )

    @staticmethod
    def _quota_issues(
        request: GenerationRequest,
        candidates: tuple[GeneratedCandidate, ...],
        generated_count: int,
    ) -> tuple[CandidateIssue, ...]:
        issues: list[CandidateIssue] = []
        parsed = [item.case for item in candidates if item.case is not None]
        if generated_count != request.count:
            issues.append(CandidateIssue(
                path="cases",
                code="generated_count_mismatch",
                message=f"请求 {request.count} 条，模型返回 {generated_count} 条",
            ))
        actual_categories = defaultdict(int)
        actual_difficulties = defaultdict(int)
        for case in parsed:
            actual_categories[case.category.value] += 1
            actual_difficulties[case.difficulty.value] += 1
        expected_categories = request.category_counts.model_dump()
        expected_difficulties = request.difficulty_counts.model_dump()
        if any(actual_categories[key] != value for key, value in expected_categories.items()):
            issues.append(CandidateIssue(
                path="cases.category",
                code="category_quota_mismatch",
                message="模型返回的用例分类数量与请求不一致",
            ))
        if any(actual_difficulties[key] != value for key, value in expected_difficulties.items()):
            issues.append(CandidateIssue(
                path="cases.difficulty",
                code="difficulty_quota_mismatch",
                message="模型返回的难度数量与请求不一致",
            ))
        if request.turn_mode == TurnMode.MIXED and request.turn_counts is not None:
            single = sum(len(case.turns) == 1 for case in parsed)
            multi = sum(len(case.turns) > 1 for case in parsed)
            if single != request.turn_counts.single or multi != request.turn_counts.multi:
                issues.append(CandidateIssue(
                    path="cases.turns",
                    code="turn_quota_mismatch",
                    message="模型返回的单轮/多轮数量与请求不一致",
                ))
        return tuple(issues)

    def validate_candidate(
        self,
        dataset_id: str,
        draft_id: str,
        draft_hash: str,
        target_ref: TargetRef,
        target_descriptor_sha256: str,
        recipe_version: str,
        acceptance_token: str,
        candidate_id: str,
        slot_index: int,
        case: Case,
    ) -> GeneratedCandidate:
        draft = self._draft(dataset_id, draft_id, draft_hash)
        descriptor = self.targets.resolve(target_ref)
        if descriptor.descriptor_sha256 != target_descriptor_sha256:
            raise DatasetGenerationError("descriptor_conflict", "评测对象能力信息已变化")
        _, issued_at, slots, _ = self._verify_acceptance_token(
            acceptance_token,
            draft_id,
            draft_hash,
            target_ref,
            target_descriptor_sha256,
            recipe_version,
        )
        if int(time.time()) - issued_at > ACCEPTANCE_TOKEN_TTL_SECONDS:
            raise DatasetGenerationError(
                "acceptance_token_expired", "候选审核时间已超过 2 小时，请重新生成"
            )
        if recipe_version != RECIPE_VERSION:
            raise DatasetGenerationError("recipe_conflict", "生成规则版本已变化，请重新生成")
        if slot_index >= len(slots):
            raise DatasetGenerationError("invalid_generation_slot", "候选生成槽位无效")
        # The signed slot proves where the candidate came from, but its generation
        # category/difficulty/turn-mode contract is complete once the provider
        # response has passed initial validation. Human reviewers may deliberately
        # change those fields. Revalidate only the edited Case's durable Target and
        # safety contracts here.
        issues = list(validate_case_for_target(
            case,
            descriptor,
            turn_mode=None,
            max_turns_per_case=None,
        ))
        issues.extend(CandidateIssue(
            path="case", code=item.code, message=item.message,
        ) for item in instruction_issues(canonical_json(case)))
        fingerprint = case_functional_fingerprint(case)
        if fingerprint in {case_functional_fingerprint(item) for item in draft.cases}:
            issues.append(CandidateIssue(
                path="case", code="duplicate_case", message="候选与当前草稿用例功能重复"
            ))
        return GeneratedCandidate(
            candidate_id=candidate_id,
            slot_index=slot_index,
            case=case,
            issues=tuple(issues),
        )

    def accept_cases(
        self,
        dataset_id: str,
        draft_id: str,
        draft_hash: str,
        target_ref: TargetRef,
        target_descriptor_sha256: str,
        recipe_version: str,
        acceptance_token: str,
        candidates: tuple[ReviewedGeneratedCase, ...],
        idempotency_key: str,
    ) -> DatasetMutationReceipt:
        if not candidates:
            raise DatasetGenerationError("empty_selection", "至少选择一个候选用例")
        # Decode just enough to check a previously committed idempotency receipt.
        # This lets a network retry succeed even if the process restarted and its
        # ephemeral signing key changed. A first-time mutation still requires HMAC.
        model_profile_id = self._acceptance_profile_id(acceptance_token)
        request_sha256 = content_sha256({
            "dataset_id": dataset_id,
            "draft_id": draft_id,
            "draft_hash": draft_hash,
            "target_ref": target_ref.model_dump(mode="json"),
            "descriptor_sha256": target_descriptor_sha256,
            "recipe_version": recipe_version,
            "model_profile_id": model_profile_id,
            # A replay after restart cannot revalidate an old process-local HMAC,
            # so bind the receipt to the exact token that created the mutation.
            # This preserves retry semantics without accepting a modified token.
            "acceptance_token_sha256": content_sha256(acceptance_token),
            "candidates": [{
                "slot_index": item.slot_index,
                "case": item.case.model_dump(
                    mode="json", exclude={"provenance", "generation_provenance"}
                ),
            } for item in candidates],
        })
        replay = self.datasets.get_mutation_receipt(
            dataset_id, idempotency_key, request_sha256
        )
        if replay is not None:
            return replay
        verified_profile_id, issued_at, slots, _ = self._verify_acceptance_token(
            acceptance_token,
            draft_id,
            draft_hash,
            target_ref,
            target_descriptor_sha256,
            recipe_version,
        )
        if verified_profile_id != model_profile_id:
            raise DatasetGenerationError(
                "invalid_acceptance_token", "生成接收令牌无效，请重新生成候选"
            )
        if int(time.time()) - issued_at > ACCEPTANCE_TOKEN_TTL_SECONDS:
            raise DatasetGenerationError(
                "acceptance_token_expired", "候选审核时间已超过 2 小时，请重新生成"
            )
        draft = self._draft(dataset_id, draft_id, draft_hash)
        descriptor = self.targets.resolve(target_ref)
        if descriptor.descriptor_sha256 != target_descriptor_sha256:
            raise DatasetGenerationError("descriptor_conflict", "评测对象能力信息已变化")
        if recipe_version != RECIPE_VERSION:
            raise DatasetGenerationError("recipe_conflict", "生成规则版本已变化，请重新生成")
        # Accepting already-generated candidates makes no provider call. Keep the
        # recorded profile identity, but do not require a currently configured key.
        profile = self.model_profile(model_profile_id)
        issues: list[CandidateIssue] = []
        fingerprints = {case_functional_fingerprint(item) for item in draft.cases}
        seen_slot_indexes: set[int] = set()
        accepted: list[Case] = []
        provenance = GeneratedCaseProvenance(
            target_ref=target_ref,
            target_descriptor_sha256=target_descriptor_sha256,
            recipe_version=recipe_version,
            model_profile_id=model_profile_id,
            provider=profile.provider,
            requested_model=profile.model,
        )
        for index, candidate in enumerate(candidates):
            case = candidate.case
            if candidate.slot_index >= len(slots):
                issues.append(CandidateIssue(
                    path=f"candidates[{index}].slot_index",
                    code="invalid_generation_slot",
                    message="候选生成槽位无效",
                ))
                continue
            if candidate.slot_index in seen_slot_indexes:
                issues.append(CandidateIssue(
                    path=f"candidates[{index}].slot_index",
                    code="duplicate_generation_slot",
                    message="同一生成槽位不能重复接收",
                ))
                continue
            seen_slot_indexes.add(candidate.slot_index)
            case_issues = list(validate_case_for_target(
                case,
                descriptor,
                turn_mode=None,
                max_turns_per_case=None,
            ))
            if case.provenance is not None or case.generation_provenance is not None:
                case_issues.append(CandidateIssue(
                    path="provenance",
                    code="system_field_not_allowed",
                    message="候选不能提交系统来源字段",
                ))
            case_issues.extend(instruction_issues(canonical_json(case)))
            fingerprint = case_functional_fingerprint(case)
            if fingerprint in fingerprints:
                case_issues.append(CandidateIssue(
                    path="case", code="duplicate_case", message="用例功能重复"
                ))
            else:
                fingerprints.add(fingerprint)
            issues.extend(_prefix_issues(f"candidates[{index}].case", case_issues))
            accepted.append(case.model_copy(update={"generation_provenance": provenance}))
        if issues:
            raise DatasetGenerationError("candidate_validation_failed", "候选校验失败", tuple(issues))
        return self.datasets.append_generated_cases_if_current(
            dataset_id=dataset_id,
            expected_draft_id=draft_id,
            expected_content_sha256=draft_hash,
            cases_to_add=tuple(accepted),
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
        )
