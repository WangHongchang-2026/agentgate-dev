# Evaluator

The Evaluator capability owns evaluation methods and execution:

```text
evaluator/
├── evaluator_protocol.py
├── executor.py
├── hybrid.py
├── rule/
└── judge/
```

Evaluator definition and version lifecycle orchestration belongs in
`application/evaluator_management.py`. External Judge model access belongs in
`integrations/model_providers/`.

The pre-refactor implementation plan is archived under
[planning history](../history/planning-v1/evaluator-implementation-plan.md). It retains
useful JSON validation and acceptance criteria but is not implementation authority.
Implemented P1 refactor records are under [P1 history](../history/p1-demo/).
