"""Contract for dispatching an existing evaluation Run."""

from typing import Protocol


class JobDispatcher(Protocol):
    """Submit a persisted Run for execution outside the caller process."""

    def submit(self, run_id: str) -> None: ...
