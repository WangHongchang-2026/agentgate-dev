import pytest

from agentgate.domain import Trace
from agentgate.storage.sqlite import SQLiteRepository


def trace(
    trace_id: str = "a" * 32,
    run_id: str = "run",
    case_id: str = "case",
    output: str = "first",
) -> Trace:
    return Trace(
        trace_id=trace_id,
        run_id=run_id,
        case_id=case_id,
        spans=(),
        final_output={"message": output},
    )


def test_same_trace_identity_accepts_complete_snapshot_update(tmp_path):
    repository = SQLiteRepository(tmp_path / "trace-update.db")
    first = trace()
    updated = trace(output="updated")

    repository.save_trace(first)
    repository.save_trace(first)
    repository.save_trace(updated)

    assert repository.get_trace("run", "case") == updated


def test_trace_identity_cannot_move_to_another_run_or_case(tmp_path):
    repository = SQLiteRepository(tmp_path / "trace-identity.db")
    repository.save_trace(trace())

    with pytest.raises(ValueError, match="identity are immutable"):
        repository.save_trace(trace(run_id="other-run"))
    with pytest.raises(ValueError, match="identity are immutable"):
        repository.save_trace(trace(case_id="other-case"))


def test_run_and_case_reject_a_different_trace_id(tmp_path):
    repository = SQLiteRepository(tmp_path / "trace-collision.db")
    first = trace()
    repository.save_trace(first)

    with pytest.raises(ValueError, match="already have a different Trace"):
        repository.save_trace(trace(trace_id="b" * 32))
    assert repository.get_trace("run", "case") == first


def test_trace_queries_are_optional_and_deterministically_ordered(tmp_path):
    repository = SQLiteRepository(tmp_path / "trace-list.db")
    second = trace(trace_id="b" * 32, case_id="case-b")
    first = trace(trace_id="a" * 32, case_id="case-a")
    repository.save_trace(second)
    repository.save_trace(first)

    assert repository.get_trace("run", "missing") is None
    assert repository.list_traces("run") == [first, second]
