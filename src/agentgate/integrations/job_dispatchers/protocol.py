"""Contract for dispatching an existing evaluation Run."""

from typing import Protocol


class JobDispatcher(Protocol):
    """Control execution of a persisted Run outside the caller process."""

    def submit(self, run_id: str) -> None: ...

    def cancel(self, run_id: str) -> None: ...
