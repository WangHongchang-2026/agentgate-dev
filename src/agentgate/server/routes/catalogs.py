"""Read-only Target-version discovery for the AgentGate demo interface."""

from fastapi import APIRouter

from agentgate.demo.loan import LoanAgent


router = APIRouter(prefix="/api", tags=["catalogs"])

_TARGET_VERSION_LABELS = {
    "loan-agent-v1-risky": "Risky version",
    "loan-agent-v2-fixed": "Fixed version",
}


@router.get("/versions")
def target_versions() -> list[dict[str, str]]:
    return [
        {"id": version, "label": _TARGET_VERSION_LABELS[version]}
        for version in LoanAgent.versions
    ]
