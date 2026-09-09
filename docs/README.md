# AgentGate Documentation

## Current Authority

- [Project progress](project-progress.md) is the current implementation checklist and
  records where each capability exists or will be added.
- [Product requirements](product-requirements-zh.md) define the intended product behavior.
- [Refactor-1 architecture](architecture.md) is the authoritative target structure.
- [Architecture review ledger](architecture-review-ledger.md) records detailed decisions
  and reconciliation notes.
- [Refactor-1 implementation plan](refactor-implementation-plan.md) maps the working
  `goal/p1-demo` behavior into the target structure and defines the execution order.
- Capability plans define file-by-file implementation decisions. The active asynchronous
  execution work is defined by the [Job Dispatcher plan](job-dispatcher/implementation-plan.md).
- Running `refactor-1` code and automated tests define implemented behavior. Target
  structures in architecture documents do not imply that every listed module exists.

Detailed implementation plans must follow the consolidated architecture and ledger.

## Current Module Documents

| Capability | Documentation | Responsibility |
| --- | --- | --- |
| Domain | [domain/](domain/) | Stable business models, invariants, version identities, and immutable execution records |
| Dataset and Case | [dataset/](dataset/) | Reusable loading, formats, versioning, sampling, and generation mechanics |
| Evaluator | [evaluator/](evaluator/) | Rule, LLM Judge, Hybrid, and evaluator execution |
| Static Skill analysis | [skill-analysis/](skill-analysis/) | Agent/Skill definition conflict, confusion, and Prompt alignment analysis |
| Run | [run/](run/) | Run manifests, execution engine, process management, retry, and artifacts |
| Trace | [trace/](trace/) | Canonical Trace normalization and redaction |
| Result | [result/](result/) | Metrics, gates, reports, and Run comparison |
| Storage | [storage/](storage/) | Persistence contracts, transactions, and SQLite implementation |
| Application | [application/](application/) | Complete use-case orchestration shared by HTTP, CLI, workers, and external control planes |
| Server | [server/](server/) | FastAPI transport, dependency wiring, error mapping, and HTTP routes |
| Web architecture | [web/](web/) | Vue application structure, routing, API boundaries, and frontend rules |
| Job dispatch | [job-dispatcher/](job-dispatcher/) | Whole-Run asynchronous dispatch, worker delivery, and queue visibility |
| Scheduled Runs | [scheduler/](scheduler/) | Durable future Run eligibility and periodic queue submission |

Cross-capability orchestration belongs in `application/`. External systems are connected
through `integrations/`. Persistence implementations belong in `storage/`.

## Plan Status

The architecture review is complete and refactor implementation is in progress. Use the
[project progress checklist](project-progress.md) for current status, then follow the
linked capability plan for the active module.

Detailed implementation plans that carry a pre-refactor warning retain useful behavior,
contracts, and acceptance criteria, but their file maps are not authoritative. Update
them against the ledger before implementation.

Numeric test totals inside implementation-decision sections record the checkpoint at
which that decision was verified. They are historical evidence, not the current suite
total; the progress checklist owns the latest total.

Historical P1 and earlier planning records are under [history/](history/).
