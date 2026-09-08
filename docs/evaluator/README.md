# Evaluator

The Evaluator capability owns versioned evaluation definitions, concrete evaluation
methods, and execution. The persistent catalog lets users configure supported methods;
it does not accept uploaded Python, dynamic imports, or arbitrary executable code.

```text
evaluator/
├── evaluator_protocol.py
├── executor.py
├── models.py
├── versioning.py
├── hybrid.py
├── rule/
└── judge/
```

## Catalog lifecycle

An `Evaluator` is one stable catalog identity. An `EvaluatorDraft` is its complete
editable definition, and publishing the draft creates an immutable, content-addressed
`EvaluatorSpec`. The first publication is version `"1"`; later publications increment
without replacing earlier versions.

Built-in identities and specifications are source-controlled, always enabled, and
read-only. They have explicit stable timestamps and are not copied into SQLite. User
identities, their one optional draft, and all published versions are stored in SQLite. A
new user Evaluator starts disabled and cannot be enabled until it has a publication.
Published Evaluators cannot be deleted; disabling prevents new Run selection while
preserving exact-version reads and historical execution.

`application/evaluator_management.py` coordinates identity, draft, publication, and
selection workflows. Pure draft transformations live in `evaluator/versioning.py`, while
the repository owns atomic publication and version allocation. Every API, CLI, and worker
composition supplies the same repository used for its Runs; there is no process-global
catalog instance.

## Validation and execution

Publishing checks that the configured implementation ID, implementation version, and
Evaluator kind match a deployment-supported implementation. Rule configuration is empty
for the current implementations. Answer-quality Judge configuration is validated against
the process-configured provider without invoking the model. Hybrid definitions must
reference exact published Rule and Judge child versions.

When evaluator IDs are omitted, a new Run retains the default built-in set. Explicit
built-in and enabled user IDs resolve to exact specifications; user IDs use their latest
publication. Those specifications are embedded unchanged in `RunManifest`. A worker
executes the manifest snapshot and never substitutes a newer publication or consults the
current enabled state.

External Judge model access belongs in `integrations/model_providers/`. Runtime execution
and failure isolation remain in `evaluator/executor.py`.

## HTTP API

The clean-break catalog boundary is under `/api/evaluators`:

```text
GET    /api/evaluators
POST   /api/evaluators
GET    /api/evaluators/{evaluator_id}
PATCH  /api/evaluators/{evaluator_id}
DELETE /api/evaluators/{evaluator_id}
GET    /api/evaluators/{evaluator_id}/versions
GET    /api/evaluators/{evaluator_id}/versions/{version}
GET    /api/evaluators/{evaluator_id}/drafts/current
POST   /api/evaluators/{evaluator_id}/drafts
PUT    /api/evaluators/{evaluator_id}/drafts/current
DELETE /api/evaluators/{evaluator_id}/drafts/current
POST   /api/evaluators/{evaluator_id}/drafts/publish
```

The POC does not include tenant isolation, persistent model-provider administration,
custom evaluator code, catalog import/export, or the Evaluator Web workspace.

The pre-refactor implementation plan is archived under
[planning history](../history/planning-v1/evaluator-implementation-plan.md). It retains
useful JSON validation and acceptance criteria but is not implementation authority.
Implemented P1 refactor records are under [P1 history](../history/p1-demo/).
