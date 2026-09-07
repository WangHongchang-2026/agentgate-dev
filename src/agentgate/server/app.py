"""AgentGate FastAPI application construction and ASGI entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentgate.integrations.job_dispatchers import JobDispatcher
from agentgate.server.dependencies import build_dependencies
from agentgate.server.routes import catalogs, datasets, results, runs, system, telemetry


def create_app(
    database_path: str | Path | None = None,
    dispatcher: JobDispatcher | None = None,
) -> FastAPI:
    """Build one AgentGate HTTP application with isolated dependencies."""

    dependencies = build_dependencies(database_path, dispatcher)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        dependencies.runs.fail_stale_runs()
        yield

    application = FastAPI(
        title="AgentGate",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.state.dependencies = dependencies
    application.include_router(system.router)
    application.include_router(datasets.router)
    application.include_router(catalogs.router)
    application.include_router(runs.router)
    application.include_router(results.router)
    application.include_router(telemetry.router)
    return application


app = create_app()
