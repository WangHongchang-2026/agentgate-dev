"""Idempotent bootstrap for the deterministic loan demonstration."""

from agentgate.application.target_catalog import TargetCatalog
from agentgate.demo.loan import LOAN_DATASET, LOAN_DATASET_VERSION
from agentgate.demo.targets import LOAN_AGENT_DESCRIPTORS
from agentgate.storage.repository import AgentGateRepository


def ensure_demo_dataset(repository: AgentGateRepository) -> None:
    """Store the demo Dataset and publication when either is not present."""

    dataset = repository.get_dataset(LOAN_DATASET.id)
    version = repository.get_published_dataset_version(
        LOAN_DATASET.id, LOAN_DATASET_VERSION.version or 0
    )
    if dataset is None:
        repository.save_dataset_with_version(LOAN_DATASET, LOAN_DATASET_VERSION)
    elif version is None:
        repository.save_dataset_version(LOAN_DATASET_VERSION)


def ensure_demo_target_descriptors(catalog: TargetCatalog) -> None:
    """Store every immutable Loan Agent descriptor idempotently."""

    for descriptor in LOAN_AGENT_DESCRIPTORS:
        catalog.register_descriptor(descriptor)
