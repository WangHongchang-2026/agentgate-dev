# Run

The Run capability owns deterministic execution mechanics:

The tree below is the target structure. `engine.py` and `target_protocol.py` are
implemented; optional process, retry, and Artifact modules are created only with real
callers. Current status is tracked in [project progress](../project-progress.md).

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

Detailed plans:

- [Run implementation](implementation-plan.md)
- [Job Dispatcher implementation](../job-dispatcher/implementation-plan.md)
- [External target integration](../history/planning-v1/external-target-plan.md)
- [Instrumented Demo Agent](../history/planning-v1/demo-agent-plan.md)

The archived plans retain useful contracts and acceptance criteria, but their pre-refactor file
maps are not authoritative.
