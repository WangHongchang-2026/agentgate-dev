# Web Architecture

The AgentGate Web application is a Chinese Vue 3 interface for evaluation workflows. It
calls the FastAPI server and never imports backend code or accesses persistence directly.

This document defines the target Web structure. Only the Dataset workspace foundation is
currently split into a page. See [`../project-progress.md`](../project-progress.md) for
implemented pages and current work.

## Stack

- Vue 3 and TypeScript
- Vite
- Element Plus
- Vue Router
- Playwright for desktop and mobile workflows

Pinia is not required initially. Page-local state and composables are sufficient until
multiple routes genuinely share mutable client state.

## Target Structure

```text
web/src/
├── main.ts
├── App.vue
├── router/
│   └── index.ts
├── layouts/
│   └── AppLayout.vue
├── pages/
│   ├── OverviewPage.vue
│   ├── RunWorkspacePage.vue
│   ├── ResultCenterPage.vue
│   ├── ResultDetailPage.vue
│   ├── DatasetWorkspacePage.vue
│   ├── EvaluatorWorkspacePage.vue
│   ├── SkillAnalysisPage.vue
│   └── OptimizerPage.vue          future
├── components/
│   ├── shared/
│   ├── run/
│   ├── result/
│   ├── dataset/
│   └── skill-analysis/
├── composables/
│   ├── useRunProgress.ts
│   └── useDatasetWorkspace.ts
├── api/
│   ├── client.ts
│   ├── runs.ts
│   ├── datasets.ts
│   ├── catalogs.ts
│   ├── results.ts
│   └── skillAnalysis.ts
├── types/
│   ├── common.ts
│   ├── target.ts
│   ├── dataset.ts
│   ├── evaluator.ts
│   ├── run.ts
│   ├── result.ts
│   ├── trace.ts
│   └── skillAnalysis.ts
└── styles/
    ├── tokens.css
    └── base.css
```

## Responsibilities

- `main.ts` initializes Vue, Element Plus, and Vue Router.
- `App.vue` mounts the application layout and current router view; it owns no evaluation
  business workflow.
- `router/` maps URLs to pages and owns redirects, route parameters, guards, and lazy
  loading.
- `layouts/` owns the application frame, sidebar, header, and responsive navigation.
- `pages/` composes one complete user workflow for each route.
- `components/` contains reusable presentation and editing controls grouped by feature.
- `composables/` contains reusable stateful frontend workflow logic.
- `api/` contains HTTP transport and endpoint functions only.
- `types/` contains frontend API request and response contracts, not duplicated backend
  business validation.
- `styles/` contains shared design tokens and global base rules; feature styles remain
  scoped to their components where practical.

## Routes And Pages

```text
/                 OverviewPage              system and evaluation overview
/runs             RunWorkspacePage          start evaluations and monitor tasks
/results          ResultCenterPage          browse completed and failed Runs
/results/:runId   ResultDetailPage          metrics, Badcases, evidence, and Trace
/datasets         DatasetWorkspacePage       Dataset, version, and Case management
/evaluators       EvaluatorWorkspacePage     Rule, Judge, and Hybrid definitions
/skill-analysis   SkillAnalysisPage          static Skill evaluation
/optimizer        OptimizerPage              deferred optimization center
```

The target POC therefore has seven planned pages and one deferred page. A route maps a URL to a
page component. Pages may compose many components, but components do not define routes.

Trace inspection remains within Result detail rather than becoming a primary page.
Starting a Run, listing active Runs, and monitoring progress remain one Run workspace for
the POC; a separate `/runs/new` route is unnecessary.

## State And Data Flow

```text
Vue Router
    |
    v
Page -> composable -> API module -> FastAPI
  |                                  |
  +---- components via props/events  +-> application layer
```

- Pages coordinate loading, empty, error, and success states.
- API calls belong in pages or composables, not low-level presentation components.
- Components receive data through typed props and report user actions through typed
  events.
- URL parameters identify shareable resources such as a Run result.
- Server data remains authoritative; the client must not reproduce domain lifecycle or
  release-gate rules.
- Long-running Run progress uses polling or server streaming through
  `useRunProgress.ts`; it must not block the browser request until the full evaluation
  completes.

## Refactor Notes

- Replace manual `history.pushState` navigation in the inherited `App.vue` with Vue
  Router.
- Move sidebar and page-frame behavior into `layouts/AppLayout.vue`.
- Split the inherited evaluation content from `App.vue` into Run and Result pages.
- Move the Dataset workspace state and API orchestration into
  `useDatasetWorkspace.ts`; preserve the existing Dataset child components where their
  boundaries remain useful.
- Split the broad `api/client.ts` into transport plus capability-specific endpoint
  modules.
- Split shared API contracts from the existing Dataset-only type organization.
- Preserve the working responsive sidebar and desktop/mobile behavior during migration.

## Rules

1. Visible product text is Chinese; source identifiers remain English.
2. `App.vue` and layout components contain no Run, Result, Dataset, or Evaluator workflow.
3. Pages do not call `fetch` directly; they use typed API modules.
4. API modules do not show messages, mutate Vue state, or render UI.
5. Components do not duplicate backend domain invariants.
6. Add a global store only for proven cross-route mutable state, not as a default layer.
7. Keep result evidence and Trace data inspectable from failed Cases.
8. Preserve stable layout dimensions and responsive behavior on desktop and mobile.
9. Playwright tests cover user workflows through the real FastAPI API, including routing.
10. Deferred pages are not implemented as hard-coded mock functionality in production
    paths.
