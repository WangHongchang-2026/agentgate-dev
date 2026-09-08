"""Process-level environment configuration for one POC Judge model."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from .openai_compatible import OpenAICompatibleModelClient


PROVIDER_ID_ENV = "AGENTGATE_JUDGE_PROVIDER_ID"
BASE_URL_ENV = "AGENTGATE_JUDGE_BASE_URL"
API_KEY_ENV = "AGENTGATE_JUDGE_API_KEY"
MODEL_ID_ENV = "AGENTGATE_JUDGE_MODEL_ID"
_REQUIRED_ENVIRONMENT = (
    PROVIDER_ID_ENV,
    BASE_URL_ENV,
    API_KEY_ENV,
    MODEL_ID_ENV,
)


def _required_value(environ: Mapping[str, str], name: str) -> str:
    value = environ[name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ConfiguredJudgeModel:
    """Safe metadata and live client built from Judge environment settings."""

    provider_id: str
    model_id: str
    credential_ref: str
    client: OpenAICompatibleModelClient


def load_judge_model_from_environment(
    environ: Mapping[str, str] | None = None,
) -> ConfiguredJudgeModel | None:
    """Build one Judge model client, or return None when entirely unconfigured."""

    source = os.environ if environ is None else environ
    present = {name for name in _REQUIRED_ENVIRONMENT if name in source}
    if not present:
        return None
    missing = set(_REQUIRED_ENVIRONMENT).difference(present)
    if missing:
        raise ValueError(
            "incomplete Judge environment; missing: "
            + ", ".join(sorted(missing))
        )

    provider_id = _required_value(source, PROVIDER_ID_ENV)
    base_url = _required_value(source, BASE_URL_ENV)
    api_key = _required_value(source, API_KEY_ENV)
    model_id = _required_value(source, MODEL_ID_ENV)
    return ConfiguredJudgeModel(
        provider_id=provider_id,
        model_id=model_id,
        credential_ref=f"env:{API_KEY_ENV}",
        client=OpenAICompatibleModelClient(
            provider_id=provider_id,
            base_url=base_url,
            api_key=api_key,
        ),
    )


__all__ = ["ConfiguredJudgeModel", "load_judge_model_from_environment"]
