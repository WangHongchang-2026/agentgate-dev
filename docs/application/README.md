# Application

The Application layer coordinates complete AgentGate use cases. It connects Domain
models, core capabilities, storage contracts, and external integrations without owning
their implementation details.

```text
Server / CLI / Worker / External control plane
                    |
                    v
              application/
                    |
        +-----------+-----------+
        v           v           v
     domain/      run/       result/
        |                       |
        +-----------> storage/ <-+
                    |
                    v
              integrations/
```

Implementation sequence: [implementation-plan.md](implementation-plan.md).
