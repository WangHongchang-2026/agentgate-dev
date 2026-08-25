# Dataset and Case

Dataset and Case ownership is split by layer:

```text
domain/                         Dataset/Case models and invariants
case/                           Reusable loading, export, versioning, sampling,
                                generation, and format mechanics
application/dataset_management.py
                                User-facing Dataset/Case lifecycle orchestration
storage/                        Persistence implementations
server/ and cli/                Transport entry points
```

The existing detailed [implementation plan](implementation-plan.md) contains useful
behavior and acceptance criteria, but its pre-refactor file map is not authoritative.

Automatic generation is a separate application use case that coordinates Target metadata,
`case/generation/`, a model provider, and Dataset draft creation.
