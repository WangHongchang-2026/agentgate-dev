from __future__ import annotations

from itertools import combinations

import pytest

from agentgate.integrations.model_providers.environment import (
    API_KEY_ENV,
    BASE_URL_ENV,
    MODEL_ID_ENV,
    PROVIDER_ID_ENV,
    ConfiguredJudgeModel,
    load_judge_model_from_environment,
)


COMPLETE_ENVIRONMENT = {
    PROVIDER_ID_ENV: "company-llm",
    BASE_URL_ENV: "https://models.example/v1",
    API_KEY_ENV: "top-secret",
    MODEL_ID_ENV: "judge-model",
}
ENVIRONMENT_NAMES = tuple(COMPLETE_ENVIRONMENT)
PARTIAL_ENVIRONMENTS = [
    {name: COMPLETE_ENVIRONMENT[name] for name in selected}
    for size in range(1, len(ENVIRONMENT_NAMES))
    for selected in combinations(ENVIRONMENT_NAMES, size)
]


def test_returns_none_when_judge_environment_is_absent() -> None:
    assert load_judge_model_from_environment({}) is None


def test_builds_safe_configured_judge_model() -> None:
    environment = dict(COMPLETE_ENVIRONMENT)

    configured = load_judge_model_from_environment(environment)

    assert isinstance(configured, ConfiguredJudgeModel)
    assert configured.provider_id == "company-llm"
    assert configured.model_id == "judge-model"
    assert configured.credential_ref == "env:AGENTGATE_JUDGE_API_KEY"
    assert configured.client.provider_id == "company-llm"
    assert configured.client.base_url == "https://models.example/v1"
    assert "top-secret" not in repr(configured)
    assert environment == COMPLETE_ENVIRONMENT
    configured.client.close()


@pytest.mark.parametrize("environment", PARTIAL_ENVIRONMENTS)
def test_rejects_every_partial_environment(
    environment: dict[str, str],
) -> None:
    missing = sorted(set(ENVIRONMENT_NAMES).difference(environment))

    with pytest.raises(ValueError, match="incomplete Judge environment") as raised:
        load_judge_model_from_environment(environment)

    assert all(name in str(raised.value) for name in missing)
    assert "top-secret" not in str(raised.value)


@pytest.mark.parametrize("name", ENVIRONMENT_NAMES)
def test_rejects_present_but_blank_values(name: str) -> None:
    environment = dict(COMPLETE_ENVIRONMENT)
    environment[name] = " "

    with pytest.raises(ValueError, match=name) as raised:
        load_judge_model_from_environment(environment)

    assert "top-secret" not in str(raised.value)
