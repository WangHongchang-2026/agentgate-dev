# Dataset and Case

The current runtime owns reusable evaluation data: Dataset identity, immutable Dataset
versions, Cases, expected outcomes, validation, import/export, and regression-set
workflows.

Detailed plans:

- [Dataset and Case management](implementation-plan.md)
- [Automatic Dataset generation](automatic-generation-plan.md)
- [Automatic generation implementation status and remaining plan](automatic-generation-implementation-plan.md)
- [Regression-set workflow](regression-set-plan.md)
- [Regression-set design record](regression-set-design.md)
- [Excel import/export design](import-export-plan.md)

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

Excel import/export is implemented in the Dataset service, REST API, and Web workspace.
Published versions can be downloaded as `.xlsx`; importing a workbook creates a new
Draft atomically. The `Cases` sheet accepts reordered or omitted optional columns and
requires only `case_name` and `input_json`. Blank Case/Turn IDs are generated, and blank
multi-turn order values are inferred from row order when all rows omit them. Multi-turn
rows use the same business-readable `case_id` (for example `loan-001`) as their grouping
key; ambiguous anonymous rows are rejected. Workbook, row, cell, formula, XML, active
content, and ZIP-expansion limits are enforced before persistence.

Automatic Dataset generation is implemented as an assisted Draft workflow:

1. Open a Dataset Draft and choose **AI 生成用例**.
2. Select the exact Agent or Skill version, model profile, quantity, turn mode,
   category/difficulty distribution, and an optional published reference version.
3. Review and edit the returned candidates. Candidates stay in the browser and are not
   persisted until explicitly selected.
4. Select valid candidates and add them to the Draft in one atomic operation. This never
   publishes the Draft or starts an evaluation.

The initial Target catalog intentionally contains complete fake Agent and Skill descriptors;
the read-only external-platform adapter is a later integration. The default model profile uses
Alibaba Bailian's Beijing OpenAI-compatible endpoint and `qwen3.7-plus`. Configure its standard
pay-as-you-go API key either in the AI generation dialog or in the server environment:

```bash
export DASHSCOPE_API_KEY='...'
```

The paid provider smoke test is opt-in:

```bash
RUN_BAILIAN_SMOKE=1 PYTHONPATH=src python3 -m pytest -q \
  tests/test_generation_model_smoke.py
```

The UI submits the key only to the credential endpoint. The backend validates it with one minimal
model call and keeps the accepted override only in process memory; it is never returned, logged,
persisted in the database, or included in a generation request. Restarting the backend clears the
override. The environment variable remains the POC server-side fallback. The generator sends a
redacted capability/reference payload, requests strict JSON Schema output, validates each candidate
against the Case and Target contracts, blocks forbidden topics, and performs exact functional
deduplication. Accepted Cases record immutable generation provenance.

Generation-related REST endpoints:

```text
GET  /api/targets?target_type=agent|skill
GET  /api/targets/{platform_id}/{target_type}/{target_id}/versions
GET  /api/dataset-generation/model-profiles
PUT  /api/dataset-generation/model-profiles/{profile_id}/credential
DELETE /api/dataset-generation/model-profiles/{profile_id}/credential
POST /api/datasets/{dataset_id}/drafts/generate-candidates
POST /api/datasets/{dataset_id}/drafts/generated-candidates/validate
POST /api/datasets/{dataset_id}/drafts/cases/batch
```

Batch acceptance requires `Idempotency-Key` plus the current Draft ID/content hash. Each selected
Case remains bound to its signed generation slot, so review edits cannot bypass the requested
category, difficulty, single/multi-turn mode, or maximum-turn constraints. A stale Draft or changed
Target descriptor returns `409` instead of overwriting newer content.
