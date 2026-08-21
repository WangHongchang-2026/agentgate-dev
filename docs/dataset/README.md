# Dataset and Case

This module owns reusable evaluation data: Dataset identity, immutable Dataset versions,
Cases, expected outcomes, validation, and import/export.

Current detailed plan: [implementation-plan.md](implementation-plan.md).

Code ownership:

- `src/agentgate/domain/case.py`: persisted Dataset and Case data models.
- `src/agentgate/domain/expectation.py`: expected outcomes and comparison conditions.
- `src/agentgate/case/`: Dataset/Case application logic.
- `src/agentgate/storage/`: persistence interfaces and adapters.
- `src/agentgate/control_plane/` and `src/agentgate/server/`: services and APIs used by CLI and Web UI.

The current vertical slice persists Datasets and immutable versions in SQLite. The seeded
loan Dataset is published version 1; user-created drafts and Cases are managed through
`DatasetService`, FastAPI, and the Chinese `/datasets` workspace.

Implemented workflow:

```text
Create/copy Dataset
  -> edit single-turn or multi-turn Cases
  -> validate and publish an immutable version
  -> run that exact version
  -> inspect expected/actual checks and turn-aware Trace
  -> create the next draft without changing historical Runs
```
