import pytest

from agentgate.demo.loan import HIGH_RISK_CASE, LOAN_DATASET_VERSION, LoanAgent
from agentgate.run.core import RunEngine
from agentgate.storage.sqlite import SQLiteRepository


def two_case_dataset():
    second = HIGH_RISK_CASE.model_copy(update={
        "id": "second-high-risk",
        "name": "第二个高风险申请",
    })
    return LOAN_DATASET_VERSION.model_copy(update={
        "cases": (HIGH_RISK_CASE, second),
        "content_sha256": "",
    })


def test_engine_executes_only_selected_case(tmp_path):
    repository = SQLiteRepository(tmp_path / "selected.db")
    dataset = two_case_dataset()
    selected = dataset.cases[1]

    run = RunEngine(repository).run(
        dataset,
        LoanAgent(repository),
        "loan-agent-v2-fixed",
        selected_case_ids=(selected.id,),
        parent_run_id="parent",
        root_run_id="root",
        rerun_case_id=selected.id,
    )

    assert run.snapshot.selected_case_ids == (selected.id,)
    assert run.parent_run_id == "parent"
    assert run.root_run_id == "root"
    assert run.rerun_case_id == selected.id
    assert {trace.case_id for trace in repository.list_traces(run.id)} == {selected.id}
    assert {result.case_id for result in repository.list_results(run.id)} == {selected.id}


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        ((), "cannot be empty"),
        (("missing",), "unknown selected Cases"),
        ((HIGH_RISK_CASE.id, HIGH_RISK_CASE.id), "must be unique"),
    ],
)
def test_engine_rejects_invalid_case_selection(tmp_path, selection, message):
    repository = SQLiteRepository(tmp_path / "invalid.db")
    with pytest.raises(ValueError, match=message):
        RunEngine(repository).run(
            two_case_dataset(),
            LoanAgent(repository),
            "loan-agent-v2-fixed",
            selected_case_ids=selection,
        )

    assert repository.list_runs() == []
