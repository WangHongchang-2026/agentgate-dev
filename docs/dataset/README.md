# Dataset and Case

Dataset and Case ownership is split by layer:

```text
domain/case.py                  Individual Case and multi-turn conversation models
domain/dataset.py               Dataset aggregate, versions, and collection invariants
dataset/                        Reusable loading, export, versioning, sampling,
                                generation, and format mechanics
application/dataset_management.py
                                User-facing Dataset/Case lifecycle orchestration
storage/                        Persistence implementations
server/ and cli/                Transport entry points
```

The pre-refactor implementation plan is archived under
[planning history](../history/planning-v1/dataset-implementation-plan.md). It retains
behavior and acceptance criteria but is not implementation authority.

Automatic generation is a separate application use case that coordinates Target metadata,
`dataset/generation/`, a model provider, and Dataset draft creation.
