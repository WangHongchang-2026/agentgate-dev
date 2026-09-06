# Trace

The Trace core owns canonical semantic conversion and protection:

Normalization and OTel integrations are implemented. `redaction.py` and obsolete
scaffold cleanup remain pending. See [project progress](../project-progress.md).

```text
trace/
├── normalizer.py
└── redaction.py
```

OTLP transport and vendor-specific trace retrieval belong in
`integrations/observability/`. Domain Trace models and invariants belong in `domain/`;
persistence belongs in `storage/`.

The [archived ingestion plan](../history/planning-v1/trace-ingestion-plan.md) retains useful correlation, merge, completeness,
and acceptance design, but its pre-refactor ownership and file map are not authoritative.

Active plan:

- [Trace implementation](implementation-plan.md)
