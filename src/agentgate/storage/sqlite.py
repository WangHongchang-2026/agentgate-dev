from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from agentgate.domain import (
    Dataset, DatasetVersion, DatasetVersionStatus, Result, Run, Trace, canonical_json,
)


class SQLiteRepository:
    """SQLite JSON-document adapter behind a PostgreSQL-compatible domain boundary."""

    def __init__(self, path: str | Path = "agentgate.db") -> None:
        self.path = str(path)
        self._transaction_connection: ContextVar[sqlite3.Connection | None] = ContextVar(
            "transaction_connection", default=None
        )
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    archived INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS dataset_versions (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id),
                    version INTEGER,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_dataset_published_version
                    ON dataset_versions(dataset_id, version)
                    WHERE status='published';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_dataset_active_draft
                    ON dataset_versions(dataset_id)
                    WHERE status='draft';
                CREATE INDEX IF NOT EXISTS idx_dataset_versions_dataset
                    ON dataset_versions(dataset_id, status, version);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS traces (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    payload TEXT NOT NULL, UNIQUE(run_id, case_id)
                );
                CREATE TABLE IF NOT EXISTS results (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS business_state (
                    namespace TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(namespace, key)
                );
                CREATE INDEX IF NOT EXISTS idx_traces_run ON traces(run_id);
                CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id);
                """
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        transaction_connection = self._transaction_connection.get()
        if transaction_connection is not None:
            yield transaction_connection
            return
        with self._connect() as connection:
            yield connection

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._transaction_connection.get() is not None:
            yield
            return
        with self._connect() as connection:
            token = self._transaction_connection.set(connection)
            try:
                yield
            finally:
                self._transaction_connection.reset(token)

    @staticmethod
    def _json(model: Any) -> str:
        return canonical_json(model)

    def save_dataset(self, dataset: Dataset) -> None:
        with self._connection() as db:
            db.execute(
                """
                INSERT INTO datasets(id,name,archived,updated_at,payload)
                VALUES(?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    archived=excluded.archived,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    dataset.id, dataset.name, int(dataset.archived),
                    dataset.updated_at.isoformat(), self._json(dataset),
                ),
            )

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM datasets WHERE id=?", (dataset_id,)
            ).fetchone()
        return Dataset.model_validate_json(row[0]) if row else None

    def list_datasets(self, include_archived: bool = False) -> list[Dataset]:
        query = "SELECT payload FROM datasets"
        if not include_archived:
            query += " WHERE archived=0"
        query += " ORDER BY updated_at DESC, id"
        with self._connect() as db:
            rows = db.execute(query).fetchall()
        return [Dataset.model_validate_json(row[0]) for row in rows]

    def save_dataset_version(self, version: DatasetVersion) -> None:
        with self._connection() as db:
            existing = db.execute(
                "SELECT payload FROM dataset_versions WHERE id=?", (version.id,)
            ).fetchone()
            if existing:
                stored = DatasetVersion.model_validate_json(existing[0])
                if stored.status == DatasetVersionStatus.PUBLISHED:
                    if stored != version:
                        raise ValueError("published DatasetVersion is immutable")
                    return
            if version.status == DatasetVersionStatus.PUBLISHED:
                conflict = db.execute(
                    """
                    SELECT payload FROM dataset_versions
                    WHERE dataset_id=? AND version=? AND status='published'
                    """,
                    (version.dataset_id, version.version),
                ).fetchone()
                if conflict:
                    stored = DatasetVersion.model_validate_json(conflict[0])
                    if stored != version:
                        raise ValueError("published Dataset version number already exists")
                    return
            db.execute(
                """
                INSERT INTO dataset_versions(
                    id,dataset_id,version,status,created_at,content_sha256,payload
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    version=excluded.version,
                    status=excluded.status,
                    content_sha256=excluded.content_sha256,
                    payload=excluded.payload
                """,
                (
                    version.id, version.dataset_id, version.version, version.status.value,
                    version.created_at.isoformat(), version.content_sha256, self._json(version),
                ),
            )

    def get_dataset_version(self, dataset_id: str, version: int) -> DatasetVersion | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload FROM dataset_versions
                WHERE dataset_id=? AND version=? AND status='published'
                """,
                (dataset_id, version),
            ).fetchone()
        return DatasetVersion.model_validate_json(row[0]) if row else None

    def get_latest_dataset_version(self, dataset_id: str) -> DatasetVersion | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload FROM dataset_versions
                WHERE dataset_id=? AND status='published'
                ORDER BY version DESC LIMIT 1
                """,
                (dataset_id,),
            ).fetchone()
        return DatasetVersion.model_validate_json(row[0]) if row else None

    def get_dataset_draft(self, dataset_id: str) -> DatasetVersion | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload FROM dataset_versions
                WHERE dataset_id=? AND status='draft'
                """,
                (dataset_id,),
            ).fetchone()
        return DatasetVersion.model_validate_json(row[0]) if row else None

    def list_dataset_versions(
        self, dataset_id: str, include_draft: bool = True
    ) -> list[DatasetVersion]:
        query = "SELECT payload FROM dataset_versions WHERE dataset_id=?"
        if not include_draft:
            query += " AND status='published'"
        query += " ORDER BY CASE status WHEN 'draft' THEN 0 ELSE 1 END, version DESC"
        with self._connect() as db:
            rows = db.execute(query, (dataset_id,)).fetchall()
        return [DatasetVersion.model_validate_json(row[0]) for row in rows]

    def delete_dataset_draft(self, dataset_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM dataset_versions WHERE dataset_id=? AND status='draft'",
                (dataset_id,),
            )

    def publish_dataset_draft(
        self, dataset_id: str, published_at: datetime
    ) -> DatasetVersion:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload FROM dataset_versions
                WHERE dataset_id=? AND status='draft'
                """,
                (dataset_id,),
            ).fetchone()
            if row is None:
                raise ValueError("dataset has no active draft")
            draft = DatasetVersion.model_validate_json(row[0])
            next_version = db.execute(
                """
                SELECT COALESCE(MAX(version), 0) + 1
                FROM dataset_versions WHERE dataset_id=? AND status='published'
                """,
                (dataset_id,),
            ).fetchone()[0]
            published = DatasetVersion.model_validate({
                **draft.model_dump(mode="json"),
                "id": str(uuid4()),
                "version": next_version,
                "status": DatasetVersionStatus.PUBLISHED,
                "published_at": published_at,
                "updated_at": published_at,
                "content_sha256": "",
            })
            db.execute(
                """
                INSERT INTO dataset_versions(
                    id,dataset_id,version,status,created_at,content_sha256,payload
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    published.id, published.dataset_id, published.version,
                    published.status.value, published.created_at.isoformat(),
                    published.content_sha256, self._json(published),
                ),
            )
            db.execute("DELETE FROM dataset_versions WHERE id=?", (draft.id,))
        return published

    def save_run(self, run: Run) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO runs(id,status,created_at,payload) VALUES(?,?,?,?)",
                (run.id, run.status, run.snapshot.created_at.isoformat(), self._json(run)),
            )

    def get_run(self, run_id: str) -> Run | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return Run.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 50) -> list[Run]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Run.model_validate_json(row[0]) for row in rows]

    def save_trace(self, trace: Trace) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO traces(id,run_id,case_id,payload) VALUES(?,?,?,?)",
                (trace.id, trace.run_id, trace.case_id, self._json(trace)),
            )

    def get_trace(self, run_id: str, case_id: str) -> Trace | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM traces WHERE run_id=? AND case_id=?", (run_id, case_id)
            ).fetchone()
        return Trace.model_validate_json(row[0]) if row else None

    def list_traces(self, run_id: str) -> list[Trace]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM traces WHERE run_id=? ORDER BY case_id", (run_id,)
            ).fetchall()
        return [Trace.model_validate_json(row[0]) for row in rows]

    def save_results(self, results: list[Result]) -> None:
        with self._connect() as db:
            db.executemany(
                "INSERT OR REPLACE INTO results(id,run_id,case_id,payload) VALUES(?,?,?,?)",
                [(r.id, r.run_id, r.case_id, self._json(r)) for r in results],
            )

    def list_results(self, run_id: str) -> list[Result]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM results WHERE run_id=? ORDER BY case_id,id", (run_id,)
            ).fetchall()
        return [Result.model_validate_json(row[0]) for row in rows]

    def put_business_state(self, namespace: str, key: str, value: dict) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO business_state(namespace,key,payload) VALUES(?,?,?)",
                (namespace, key, json.dumps(value, ensure_ascii=False)),
            )

    def get_business_state(self, namespace: str, key: str) -> dict | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM business_state WHERE namespace=? AND key=?", (namespace, key)
            ).fetchone()
        return json.loads(row[0]) if row else None
