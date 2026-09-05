# Storage

Storage defines persistence contracts and infrastructure implementations for AgentGate
domain objects.

```text
application/core -> storage/repository.py <- storage/sqlite.py
```

- `repository.py` defines typed persistence operations with domain models.
- `sqlite.py` implements the contract for the POC and owns SQL, constraints, indexes,
  serialization, and transactions.
- Domain and application layers own invariants and workflows; Storage does not construct
  business transitions.

Implementation sequence: [implementation-plan.md](implementation-plan.md).

