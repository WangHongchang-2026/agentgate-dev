# Run

The Run capability owns deterministic execution mechanics:

```text
run/
├── engine.py
├── process_manager.py
├── retry.py
├── manifest.py
├── artifacts.py
└── target_protocol.py
```

Complete Run lifecycle orchestration belongs in `application/run_management.py`.
Concrete Agent integrations belong in `integrations/targets/`, and Celery background
submission belongs in `integrations/job_dispatchers/`.

Detailed plans:

- [External target integration](external-target-plan.md)
- [Instrumented Demo Agent](demo-agent-plan.md)
- [Single-Case rerun refactor design](single-case-rerun-refactor-design.md)
- [Single-Case rerun refactor plan](single-case-rerun-refactor-plan.md)

These plans retain useful contracts and acceptance criteria, but their pre-refactor file
maps are not authoritative.

## Implemented Single-Case rerun flow

`application/run_management.py` owns rerun orchestration. It loads a completed source
Run, fixes the original snapshot Case and evaluation configuration, selects an explicit
Agent version, and asks the Run engine to create an independent child Run. The Run
domain model records the selected Case and parent/root lineage; the original Run,
Result, and Trace remain immutable.

The first implementation executes inline. Moving submission to a background dispatcher
does not change the rerun application contract.
