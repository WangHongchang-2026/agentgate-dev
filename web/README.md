# AgentGate Web

Chinese P1 evaluation UI backed by the AgentGate REST API.

## Implemented Workflows

- configure and submit an evaluation asynchronously;
- inspect queued and running Runs, Case progress, timing, errors, and recent history;
- poll every two seconds only while active work exists;
- open completed reports and Trace evidence;
- create, publish, version, and run Datasets.

The Web UI calls only AgentGate REST APIs. Redis, Celery, SQLite, and Python modules are
never accessed from browser code.

## Development

Install dependencies with `npm install`. Start Redis, the Celery worker, and FastAPI
using the commands in the root [README](../README.md), then run:

```bash
AGENTGATE_API_TARGET="http://127.0.0.1:8000" npm run dev
```

Verification commands:

```bash
npm run typecheck
npm run build
npm run test:e2e
```

The Playwright configuration starts an isolated Redis broker, a one-process Celery
worker, FastAPI, and Vite. It expects `redis-server` on `PATH` and Playwright Chromium
to be installed.

## Stack

- Vue 3
- TypeScript
- Vite
- Element Plus
- Playwright
