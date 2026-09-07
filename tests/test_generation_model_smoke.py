"""Explicit paid smoke test; normal CI never calls the real model provider."""

import os

import pytest

from agentgate.application.target_catalog import build_fake_target_catalog
from agentgate.case.generation.blueprint import parse_blueprint_response
from agentgate.case.generation.models import GenerationRequest
from agentgate.case.generation.recipe import build_model_request
from agentgate.domain import TargetRef, TargetType
from agentgate.integrations.model_providers import (
    OpenAICompatibleGenerationModel,
    bailian_default_profile,
)


@pytest.mark.skipif(
    os.getenv("RUN_BAILIAN_SMOKE") != "1" or not os.getenv("DASHSCOPE_API_KEY"),
    reason="set RUN_BAILIAN_SMOKE=1 and DASHSCOPE_API_KEY to run the paid smoke test",
)
def test_bailian_structured_output_generates_a_valid_fake_skill_case():
    target_ref = TargetRef(
        platform_id="fake",
        target_type=TargetType.SKILL,
        external_target_id="order-query",
        external_version_id="deployment-20260903",
    )
    request = GenerationRequest.model_validate({
        "draft_id": "smoke-draft",
        "draft_content_sha256": "smoke-hash",
        "target_ref": target_ref,
        "count": 1,
        "turn_mode": "single",
        "category_counts": {"positive": 1, "negative": 0, "boundary": 0},
        "difficulty_counts": {"easy": 1, "medium": 0, "hard": 0},
        "instructions": "生成一个普通订单查询用例",
    })
    profile = bailian_default_profile()
    descriptor = build_fake_target_catalog().resolve(target_ref)
    model_request = build_model_request(request, descriptor, (), profile)

    response = OpenAICompatibleGenerationModel().generate(model_request)
    candidates, generated_count, batch_issues = parse_blueprint_response(
        response.content, descriptor
    )

    assert generated_count == 1
    assert batch_issues == ()
    assert len(candidates) == 1
    assert candidates[0].valid
