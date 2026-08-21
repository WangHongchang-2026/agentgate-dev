# P1 Demo Progress

## Current checkpoint

The P1 loan-approval vertical slice is implemented on `goal/p1-demo`.

## Module status

Audited against the current source tree on 2026-08-19. A green marker applies only to
the behavior described in that row; it does not mean every future feature in that
package is complete.

Markers:

- ✅ Implemented and verified in the P1 demo
- 🟡 Interface or package boundary exists, but the full feature is deferred
- ⬜ Not implemented

| Status | Module | Current implementation | Code location / next work |
| --- | --- | --- | --- |
| ✅ | Domain contracts | Immutable Pydantic models for Cases, Datasets, evaluations, Runs, Traces, Results, Metrics, Gates, and reports | `src/agentgate/domain/` |
| ✅ | Dataset and Case P1 workflow | SQLite CRUD, drafts, immutable published versions, copy/reorder, validation, canonical JSON plus lossless/safety-bounded Excel import/export, multi-turn Cases, and Web editor | `src/agentgate/case/`, `src/agentgate/storage/sqlite.py`, `src/agentgate/server/application.py`, `web/src/pages/DatasetWorkspace.vue` |
| ✅ | Single-Case rerun | Reuses the original RunSnapshot Case and evaluation configuration, permits a new Demo Agent version, records rerun lineage, and compares evaluator outcomes | `src/agentgate/run/core.py`, `src/agentgate/control/core.py`, `web/src/App.vue` |
| ⬜ | Later Dataset features | Automatic Case/template generation and regression-set workflow are not implemented | Plans remain under `docs/dataset/` |
| ✅ | Evaluator kernel | Registration, plan validation, observations, operators, scoring, dependency resolution, N/A, and ERROR isolation | `src/agentgate/evaluator/` |
| ✅ | Rule evaluators | Seven rules: routing, required tool, forbidden tool, tool arguments, final state, final output, and policy compliance | `src/agentgate/evaluator/rules/` |
| 🟡 | JSON Schema evaluation | `MatchesJsonSchema` is a domain contract, but pre-run validation intentionally rejects it because no runtime operator exists | `src/agentgate/domain/expectation.py`, `src/agentgate/evaluator/validation.py` |
| ⬜ | Evaluator asset management | Evaluators are module constants; there is no evaluator CRUD repository or publish/version workflow | Future evaluator-management increment |
| 🟡 | LLM Judge | Versioned contracts are defined; execution runtime is deferred to P2 | `src/agentgate/domain/evaluation.py`, `src/agentgate/evaluator/llm_judge/README.md` |
| 🟡 | Hybrid evaluator | Versioned contract is defined; Rule + LLM Judge execution is deferred to P2 | `src/agentgate/domain/evaluation.py`, `src/agentgate/evaluator/hybrid/README.md` |
| 🟡 | External evaluator adapters | Third-party adapter files exist but contain no runtime implementation | `src/agentgate/evaluator/external/` |
| ✅ | Metrics, Gate, and Run report | Deterministic metric/dimension/kind/overall aggregation, fail-closed Gate decisions, expected/actual checks, and evidence detail | `src/agentgate/result/` |
| ⬜ | Result comparison/regression center | A/B comparison and regression workflows are not implemented | `src/agentgate/result/compare.py` is an empty boundary |
| ✅ | Local Run execution | Published Dataset execution, immutable RunSnapshot, Python-function target, local scheduler, persistence, and report construction | `src/agentgate/run/core.py` |
| 🟡 | External target integration | Target protocol exists, but HTTP, process, trace-only, framework, catalog, and external-version adapters are empty boundaries | `src/agentgate/run/targets/`, `src/agentgate/run/external/` |
| 🟡 | Scheduler | Local synchronous execution and external scheduler protocol exist; production scheduling is deferred | `src/agentgate/run/core.py`, `src/agentgate/run/scheduler.py` |
| ✅ | Control API and CLI | FastAPI and Typer use the same working `EvaluationService` | `src/agentgate/control_plane/service.py`, `src/agentgate/server/`, `src/agentgate/cli/` |
| ✅ | Chinese Web UI | Real APIs support overview, launch, report/detail, trace drill-down, and Dataset/Case editing on desktop and mobile | `web/src/` |
| ✅ | Canonical Trace and basic OTLP/HTTP | Canonical Trace persistence, normalization, and real OTLP/HTTP JSON `POST /v1/traces` ingestion | `src/agentgate/domain/trace.py`, `src/agentgate/trace/normalizer.py`, `src/agentgate/trace/receivers/otlp_http.py` |
| 🟡 | Advanced Trace ingestion | Multi-batch merge/deduplication, completeness/conflict lifecycle, protobuf, OTLP/gRPC, and importers are not implemented | `src/agentgate/trace/receivers/otlp_grpc.py`, `src/agentgate/trace/importers/` |
| ✅ | Demo target | Deterministic risky/fixed loan-agent versions, four capabilities, SQLite business state, deterministic provider, and optional OpenAI-compatible provider | `src/agentgate/demo/` |
| ⬜ | Instrumented Demo HTTP Agent | Separate HTTP service, OpenTelemetry SDK instrumentation/export, W3C context propagation, and asynchronous telemetry completion are not implemented | Planned in `docs/run/demo-agent-plan.md` |
| ✅ | SQLite persistence | Repository boundary and persisted Dataset versions, Runs, Traces, Results, and business state | `src/agentgate/storage/` |
| ⬜ | PostgreSQL | Adapter and migrations are not implemented | Future adapter under `src/agentgate/storage/` |
| 🟡 | Experiment / A/B | Package boundary only; comparison and consistency behavior are deferred | `src/agentgate/experiment/` |
| 🟡 | Queue, optimizer, lineage | Package boundaries only; full feature sets are deferred | `src/agentgate/queue/`, `src/agentgate/optimizer/`, `src/agentgate/lineage/` |
| 🟡 | Public benchmarks | Importer boundaries exist; integrations are not implemented | `src/agentgate/case/public_benchmarks/` |
| ⬜ | Static Skill analysis | Design exists, but there is no `src/agentgate/analysis/` runtime module | Planned in `docs/analysis/skill-static-analysis-plan.md` |
| ⬜ | Credential management | No credential store, secret-reference model, or authorization workflow is implemented | Future security plan |

- Focused immutable Pydantic models under `domain/` cover Expectations, Cases,
  Datasets, evaluator specifications, canonical Traces, detailed Results, Metric plans,
  Gate specifications, Runs, and reports. Nested JSON is recursively immutable.
- RunSnapshot persists the full Dataset, target, evaluator specifications, primary
  evaluator IDs, MetricPlan, GateSpec, and a canonical SHA-256 content hash.
- `AgentGateRepository` is the persistence boundary; `SQLiteRepository` persists
  Dataset catalogs and versions, runs, traces, results, and demo business state. A
  PostgreSQL adapter can implement the same protocol later.
- The demo target exposes loan approval, credit inquiry, repayment plan, and complaint capabilities. `loan-agent-v1-risky` directly approves the high-risk case; `loan-agent-v2-fixed` sends it to human review.
- Deterministic execution is the default. An optional OpenAI-compatible provider is isolated behind `AgentProvider`.
- `LocalScheduler` is the POC executor behind `ExternalSchedulerAdapter`; no production scheduler is included.
- FastAPI and Typer use the same `EvaluationService`, now located in the explicit
  `control_plane/` package. The independent `queue/`, `run/`, and `server/` boundaries
  remain in place.
- OTLP/HTTP JSON ingestion is available at `POST /v1/traces`; parsing and normalization
  live under `trace/`, while the FastAPI route only delegates. Health is separate at
  `GET /health`. OTLP/gRPC remains an intentionally reserved boundary.
- The Vue 3, TypeScript, and Element Plus UI uses real API calls for overview, launch, run
  detail, result summary, failed-case trace drill-down, and the three-column Dataset/Case
  workspace. Draft editing, immutable publishing, JSON/Excel import and export, and version-aware
  evaluation all persist through SQLite.
- Seven deterministic Rule evaluators cover routing, required tools, forbidden tools, tool
  arguments, final state, final output, and policy compliance. LLM Judge and Hybrid have version-1
  contracts but runtime execution remains P2.
- Not-applicable checks use `outcome=not_applicable` and `score=null`. Evaluator
  crashes, timeouts, and malformed output use `outcome=error`, fail the Gate closed,
  and never assign an agent failure stage.
- Failure attribution is labelled `primary_failure_step`, meaning the first
  trace-sequenced observed failing stage; it is not presented as a proven root cause.
- Report metrics expose metric, dimension, evaluator-kind, and overall summaries. Kind
  summaries are a parallel reporting view and never feed the overall score.

## Setup

Python 3.11+ and Node.js are required.

```bash
python3 -m pip install -e '.[test]'
cd web
npm install
npx playwright install chromium
npx playwright install-deps chromium
```

The dependency command may require root privileges on minimal Linux images. If sudo is
not available, ask the machine administrator to install the printed browser libraries.

The refactor intentionally does not migrate old disposable P1 payloads. Stop the backend,
rename the old SQLite file as a backup, and start with a fresh database.

## Run the demo

```bash
agentgate evaluate --version loan-agent-v1-risky --database ./agentgate.db
agentgate evaluate --version loan-agent-v2-fixed --database ./agentgate.db
AGENTGATE_DB=./agentgate.db uvicorn agentgate.server.application:app --reload
cd web && npm run dev
```

Open `http://127.0.0.1:5173`. The Vite development server proxies API calls to FastAPI at `http://127.0.0.1:8000`.

## Verification

```bash
python3 -m pytest -q
python3 -m pip wheel . --no-deps --wheel-dir /tmp/agentgate-wheel
cd web
npm audit
npm run typecheck
npm run build
npm run test:e2e
```

Current automated evidence:

- Python: 113 unit/API/CLI/integration tests pass.
- Vue TypeScript typecheck: pass.
- Vue production build: pass.
- Playwright: 18 desktop and Pixel 7 checks pass. Tests use dedicated ports 18000/15173 and
  a per-run SQLite database, so they never reuse the public demo service or old payloads.

The deterministic acceptance expectation is:

| Target version | Expected gate | Reason |
| --- | --- | --- |
| `loan-agent-v1-risky` | fail | Direct high-risk approval violates required-tool, forbidden-tool, final-state, and policy checks; the missing review tool makes its argument check not applicable. |
| `loan-agent-v2-fixed` | pass | High-risk applications enter human review and all deterministic checks pass. |

## Remaining work outside P1

- JSON Schema execution and evaluator asset management.
- External HTTP/process/trace-only targets and framework adapters.
- Instrumented Demo Agent HTTP service and OpenTelemetry SDK export.
- Advanced Trace merge, deduplication, completeness, protobuf, and correlation handling.
- PostgreSQL adapter and migrations.
- OTLP/gRPC receiver.
- Production external-scheduler integration.
- Full experiment, queue, optimizer, and lineage feature sets.
- Public benchmark integrations.
- LLM Judge and Hybrid evaluator runtime.
- A/B consistency enforcement.
- Static Skill analysis, automatic Dataset/template generation, and regression-set workflow.
- Credential management.
- Ordered-sequence operators.
