# Run

The Run capability owns deterministic execution mechanics:

The tree below is the target structure. `engine.py`, `retry.py`, and
`target_protocol.py` are implemented. The optional process and Artifact modules remain
planned until they have real callers. Current status is tracked in
[project progress](../project-progress.md).

```text
run/
├── engine.py
├── process_manager.py
├── retry.py
├── artifacts.py
└── target_protocol.py
```

Complete Run lifecycle orchestration belongs in `application/run_management.py`.
Concrete Agent integrations belong in `integrations/targets/`, and Celery background
submission belongs in `integrations/job_dispatchers/`.

Run retry is a per-Case execution policy. It retries only typed Target infrastructure
failures classified as rate limiting, timeout, or temporary unavailability. Each retry
uses a fresh execution and Trace identity with bounded exponential delay. Wrong answers,
review outcomes, evaluator failures, validation failures, and persistence failures are
never retried.

The current POC persists the successful attempt's Trace and Results. Persistent failed
attempt history and retry events in Traces remain future work.

Detailed plans:

- [Run implementation](implementation-plan.md)
- [Job Dispatcher implementation](../job-dispatcher/implementation-plan.md)
- [Scheduled Run implementation](../scheduler/implementation-plan.md)
- [External target integration](../history/planning-v1/external-target-plan.md)
- [Instrumented Demo Agent](../history/planning-v1/demo-agent-plan.md)

The archived plans retain useful contracts and acceptance criteria, but their pre-refactor file
maps are not authoritative.
