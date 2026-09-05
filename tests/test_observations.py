from agentgate.domain import (
    Equals, MustBeMissing, StateExpectation, Trace,
)
from agentgate.evaluator.observations import MISSING, observe
from agentgate.evaluator.operators.comparison import equals, must_be_missing


def test_null_and_missing_are_distinct():
    trace = Trace(trace_id="0" * 32, run_id="run", case_id="case", spans=(), final_state={"value": None})
    present = observe(trace, StateExpectation(path="value", condition=Equals(expected=None)))
    missing = observe(trace, StateExpectation(path="other", condition=MustBeMissing()))
    assert present.values == (None,)
    assert missing.values[0] is MISSING
    assert equals(present.values[0], Equals(expected=None)).passed
    assert not equals(missing.values[0], Equals(expected=None)).passed
    assert must_be_missing(missing.values[0], MustBeMissing()).passed
    assert not must_be_missing(present.values[0], MustBeMissing()).passed
