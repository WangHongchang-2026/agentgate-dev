# Documentation Index

Top-level documents describe the whole AgentGate project. Detailed design decisions,
working notes, and implementation plans live under the module that owns them.

## Project-wide documents

- [Product requirements](product-requirements-zh.md)
- [Implementation roadmap](implementation-roadmap.md)
- [Demo setup and test guide](demo-test-guide.md)
- [System architecture](arch.md)
- [Capability mapping](capability-mapping.md)
- [Verified progress](progress.md)

## Module documents

| Module | Documentation | Current source | Responsibility |
| --- | --- | --- | --- |
| Dataset and Case | [dataset/](dataset/) | `src/agentgate/case/`, `domain/case.py` | Dataset versions, Cases, import/export, and editing |
| Evaluator | [evaluator/](evaluator/) | `src/agentgate/evaluator/` | Rule, LLM Judge, Hybrid, operators, and execution |
| Static analysis | [analysis/](analysis/) | Planned | Skill conflict, confusion, and Prompt alignment |
| Run | [run/](run/) | `src/agentgate/run/` | Run snapshots and target execution |
| Trace | [trace/](trace/) | `src/agentgate/trace/` | Canonical traces and telemetry ingestion |
| Result | [result/](result/) | `src/agentgate/result/` | Scores, metrics, reports, and release gates |
| Control plane | [control-plane/design.md](control-plane/design.md) | `src/agentgate/control_plane/`, `queue/`, `server/` | Job ownership, queue and scheduler boundaries, and external execution integration |
| Control panel | [control-panel/](control-panel/) | `web/` | Web UI and application workflows |

## Documentation rule

- Keep cross-module architecture and product requirements at the docs root.
- Put a module's terminology, decisions, and implementation plan in its folder.
- Record verified project-wide status in progress.md, not in multiple module plans.
- Treat plans as design records; running code and automated tests remain authoritative.
