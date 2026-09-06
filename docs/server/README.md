# Server

The Server is AgentGate's FastAPI transport boundary. It validates HTTP input, calls
Application use cases, maps errors to HTTP responses, and serializes results.

```text
Web or external caller
        |
        v
FastAPI routes
        |
        v
application/
```

It does not execute Agents, calculate evaluation results, query SQLite directly, or own
customer scheduler behavior.

Implementation sequence: [implementation-plan.md](implementation-plan.md).
The initial synchronous route exists, but asynchronous HTTP 202 dispatch and activity
endpoints are the current target. See [project progress](../project-progress.md).
