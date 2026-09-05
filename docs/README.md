# AgentGate Documentation

## Current Authority

- [Product requirements](product-requirements-zh.md) define the intended product behavior.
- [Refactor-1 architecture](architecture.md) is the authoritative target structure.
- [Architecture review ledger](architecture-review-ledger.md) records detailed decisions
  and reconciliation notes.
- [Refactor-1 implementation plan](refactor-implementation-plan.md) maps the working
  `goal/p1-demo` behavior into the target structure and defines the execution order.
- Running code and automated tests describe the inherited `goal/p1-demo` baseline; they
  do not override confirmed refactor decisions in the ledger.

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
| Web architecture | [web/](web/) | Vue application structure, routing, API boundaries, and frontend rules |

Cross-capability orchestration belongs in `application/`. External systems are connected
through `integrations/`. Persistence implementations belong in `storage/`.

## Plan Status

The architecture review is complete. The next implementation authority is the
[Refactor-1 implementation plan](refactor-implementation-plan.md).

Detailed implementation plans that carry a pre-refactor warning retain useful behavior,
contracts, and acceptance criteria, but their file maps are not authoritative. Update
them against the ledger before implementation.

Historical P1 and earlier planning records are under [history/](history/).
