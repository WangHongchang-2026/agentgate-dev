# Demo Capability Mapping

This document maps AgentGate demo capabilities to package ownership. A package being present
means its boundary is reserved; it does not mean the capability is implemented.

## Status Values

- `scaffolded`: package boundary exists, implementation is pending
- `partial`: supporting primitives exist, end-to-end acceptance is pending
- `planned`: no implementation yet
- `complete`: acceptance criteria are implemented and verified

## Capabilities

| ID | Capability | Primary owner | Supporting modules | Status |
| --- | --- | --- | --- | --- |
| CAP-01 | Batch evaluation target coverage | `run/` | `case/`, `control_plane/` | scaffolded |
| CAP-02 | Merged Skill datasets | `case/` | `lineage/` | scaffolded |
| CAP-03 | Dedicated router-agent datasets | `case/` | `control_plane/` | scaffolded |
| CAP-04 | Agent and workflow evaluation | `run/targets/` | `trace/` | scaffolded |
| CAP-05 | Unified execution engine | `run/` | `evaluator/`, `result/` | complete |
| CAP-06 | Concurrency, timeout, sampling, retry | `run/` | `queue/` | scaffolded |
| CAP-07 | Shared and private model credentials | `queue/` | `control_plane/`, `run/` | scaffolded |
| CAP-08 | Result and relationship visualization | `web/` | `result/`, `lineage/` | partial |
| CAP-09 | Independent evaluator management | `evaluator/` | `control_plane/` | partial |
| CAP-10 | Rule, LLM Judge, and Hybrid evaluators | `evaluator/` | `result/` | partial |
| CAP-11 | Quantitative score and explanation | `evaluator/` | `result/` | complete |
| CAP-12 | Evaluator version management | `lineage/` | `evaluator/` | scaffolded |
| CAP-13 | Constrained-resource task queue | `queue/` | `run/scheduler.py` | scaffolded |
| CAP-14 | A/B experiment creation | `experiment/` | `lineage/` | scaffolded |
| CAP-15 | Controlled A/B execution | `experiment/` | `run/`, `queue/` | scaffolded |
| CAP-16 | A/B comparison report | `experiment/` | `result/` | scaffolded |
| CAP-17 | Release decision thresholds | `result/` | `experiment/` | complete |
| CAP-18 | Reproducible experiments | `experiment/` | `lineage/`, `run/snapshot.py` | scaffolded |
| CAP-19 | Badcase clustering | `optimizer/` | `result/` | scaffolded |
| CAP-20 | Root-cause analysis | `optimizer/` | `trace/` | scaffolded |
| CAP-21 | Optimization recommendations | `optimizer/` | `evaluator/`, `case/` | scaffolded |
| CAP-22 | Human review and regression loop | `optimizer/` | `experiment/`, `run/` | scaffolded |
| CAP-23 | Versioned asset lineage graph | `lineage/` | `case/versioning.py`, `web/` | scaffolded |

## Boundary Rules

- The core flow remains `Case -> Run + Trace -> Evaluator -> Result`.
- `experiment/` composes runs and results; it does not execute agents directly.
- `queue/` exposes reservation and queue operations; `run/scheduler.py` controls execution.
- `optimizer/` produces reviewable suggestions and does not mutate target assets.
- `lineage/` records immutable identities and relationships; domain modules own their content.
- Production queue execution integrates through an external scheduler adapter.
