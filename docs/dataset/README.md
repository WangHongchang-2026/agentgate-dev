# Dataset and Case

The current runtime owns reusable evaluation data: Dataset identity, immutable Dataset
versions, Cases, expected outcomes, validation, import/export, and regression-set
workflows.

Detailed plans:

- [Dataset and Case management](implementation-plan.md)
- [Regression-set workflow](regression-set-plan.md)
- [Regression-set design record](regression-set-design.md)

Current code ownership:

- `src/agentgate/domain/case.py`: persisted Dataset and Case data models.
- `src/agentgate/domain/expectation.py`: expected outcomes and comparison conditions.
- `src/agentgate/case/`: Dataset/Case application logic.
- `src/agentgate/storage/`: persistence interfaces and adapters.
- `src/agentgate/control_plane/` and `src/agentgate/server/`: services and APIs used by CLI and Web UI.

The current vertical slice persists Datasets and immutable versions in SQLite. The seeded
loan Dataset is published version 1; user-created drafts and Cases are managed through
`DatasetService`, FastAPI, and the Chinese `/datasets` workspace.

Implemented behavior includes adding a completed Run Case to a new or existing regression
Dataset, immutable source provenance, duplicate protection, and running the resulting
published Dataset through the ordinary evaluation workflow.

The confirmed refactor target moves user-facing orchestration into `application/` and
keeps `case/` for reusable mechanics. The existing detailed plans retain useful behavior
and acceptance criteria, but their pre-refactor file maps are not authoritative.

Automatic generation is a separate application use case that coordinates Target metadata,
`case/generation/`, a model provider, and Dataset draft creation.

Excel import/export and automatic Dataset generation remain deferred.
