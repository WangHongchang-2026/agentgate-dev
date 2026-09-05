# Refactor-1 Baseline Record

Recorded: 2026-09-05

## Scope

This baseline was collected before refactor-1 structural implementation. Backend source
on `review/refactor-1-architecture` is unchanged from `goal/p1-demo`. The Web working tree
contains separate uncommitted changes, so its results describe that current working tree
and those changes must not be discarded.

## Results

| Check | Command | Result |
| --- | --- | --- |
| Backend tests | `python3 -m pytest -q` | PASS: 47 tests passed; one Starlette/httpx deprecation warning |
| Web typecheck | `cd web && npm run typecheck` | PASS |
| Web production build | `cd web && npm run build` | PASS |
| Web unit tests | `cd web && npm run test -- --run` | NOT AVAILABLE: `package.json` has no `test` script |
| Web end-to-end tests | `cd web && npm run test:e2e` | ENVIRONMENT BLOCKED: 6 cases could not launch Chromium because `libatk-1.0.so.0` is missing |

The Playwright failures occurred before application assertions ran. They are not evidence
of six product failures. Install the required Chromium system libraries, then rerun the
same command to establish the browser behavior baseline.

## Build Observation

The Web build produced an approximately 1,011 kB minified JavaScript bundle (324 kB
gzip) and Vite's chunk-size warning. Refactor-1 routing should use lazy page imports so
that route-level code splitting addresses this without unrelated optimization work.

## Required Behavior Gates

During refactor, the backend suite must continue to cover:

- risky loan-Agent version fails its release gate;
- fixed loan-Agent version passes and scores higher;
- Dataset draft/publish/version workflows;
- immutable and hash-verified Run inputs;
- per-turn deterministic evaluation and failure attribution;
- persisted Runs, Traces, and Results;
- OTLP HTTP ingestion;
- API and CLI execution paths.

The browser suite becomes a required gate after its host dependencies are available.
