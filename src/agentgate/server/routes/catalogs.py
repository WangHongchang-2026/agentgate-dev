"""Read-only catalogs used by the AgentGate demo interface."""

from typing import Any

from fastapi import APIRouter

from agentgate.demo.loan import LoanAgent
from agentgate.evaluator import EVALUATORS


router = APIRouter(prefix="/api", tags=["catalogs"])

_TARGET_VERSION_LABELS = {
    "loan-agent-v1-risky": "Risky version",
    "loan-agent-v2-fixed": "Fixed version",
}
_EVALUATOR_FIELDS = {
    "id",
    "name",
    "kind",
    "version",
    "dimension",
    "metric",
    "severity",
    "implementation_id",
    "implementation_version",
    "config",
}


@router.get("/versions")
def target_versions() -> list[dict[str, str]]:
    return [
        {"id": version, "label": _TARGET_VERSION_LABELS[version]}
        for version in LoanAgent.versions
    ]


@router.get("/evaluators")
def evaluators() -> list[dict[str, Any]]:
    return [
        evaluator.model_dump(mode="json", include=_EVALUATOR_FIELDS)
        for evaluator in EVALUATORS
    ]
