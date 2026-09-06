from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from agentgate.domain import (
    Dataset, DatasetVersion, DatasetVersionStatus, EvaluationResult, EvaluationRun, Trace, canonical_json,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    archived INTEGER NOT NULL CHECK(archived IN (0, 1)),
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dataset_versions (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL REFERENCES datasets(id),
    version INTEGER,
    status TEXT NOT NULL CHECK(status IN ('draft', 'published')),
    created_at TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    payload TEXT NOT NULL,
    CHECK(
        (status = 'draft' AND version IS NULL)
        OR (status = 'published' AND version >= 1)
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dataset_published_version
    ON dataset_versions(dataset_id, version)
    WHERE status = 'published';
CREATE UNIQUE INDEX IF NOT EXISTS idx_dataset_active_draft
    ON dataset_versions(dataset_id)
    WHERE status = 'draft';
CREATE INDEX IF NOT EXISTS idx_dataset_versions_dataset
    ON dataset_versions(dataset_id, status, version);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(
        status IN ('pending', 'running', 'completed', 'failed', 'cancelled')
    ),
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS traces (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(run_id, case_id)
);
CREATE TABLE IF NOT EXISTS results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_traces_run ON traces(run_id);
CREATE INDEX IF NOT EXISTS idx_results_run ON results(run_id);
"""


class SQLiteRepository:
    """SQLite JSON-document adapter behind a PostgreSQL-compatible domain boundary."""

    def __init__(
        self, path: str | Path = "agentgate.db", busy_timeout_ms: int = 5_000
    ) -> None:
        if busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be at least 1")
        self.path = str(path)
        self.busy_timeout_ms = busy_timeout_ms
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path, timeout=self.busy_timeout_ms / 1_000
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(_SCHEMA)

    def save_dataset(self, dataset: Dataset) -> None:
        with self._connect() as db:
            existing = db.execute(
                "SELECT payload FROM datasets WHERE id = ?", (dataset.id,)
            ).fetchone()
            if existing:
                stored = Dataset.model_validate_json(existing[0])
                if dataset.created_at != stored.created_at:
                    raise ValueError("Dataset created_at is immutable")
                if dataset.updated_at < stored.updated_at:
                    raise ValueError("cannot save a stale Dataset")
                if dataset == stored:
                    return
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
                    dataset.updated_at.isoformat(), canonical_json(dataset),
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
        with self._connect() as db:
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
                    version.created_at.isoformat(), version.content_sha256,
                    canonical_json(version),
                ),
            )

    def get_published_dataset_version(
        self, dataset_id: str, version: int
    ) -> DatasetVersion | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload FROM dataset_versions
                WHERE dataset_id=? AND version=? AND status='published'
                """,
                (dataset_id, version),
            ).fetchone()
        return DatasetVersion.model_validate_json(row[0]) if row else None

    def get_latest_published_dataset_version(
        self, dataset_id: str
    ) -> DatasetVersion | None:
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

    def delete_dataset_draft(self, dataset_id: str, expected_draft_id: str) -> None:
        with self._connect() as db:
            cursor = db.execute(
                """
                DELETE FROM dataset_versions
                WHERE dataset_id=? AND id=? AND status='draft'
                """,
                (dataset_id, expected_draft_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("expected Dataset draft does not exist")

    def replace_dataset_draft(
        self, expected_draft_id: str, published: DatasetVersion
    ) -> None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT payload FROM dataset_versions
                WHERE id=? AND status='draft'
                """,
                (expected_draft_id,),
            ).fetchone()
            if row is None:
                raise ValueError("expected Dataset draft does not exist")
            draft = DatasetVersion.model_validate_json(row[0])
            if draft.dataset_id != published.dataset_id:
                raise ValueError("published DatasetVersion does not match the draft")
            if published.status != DatasetVersionStatus.PUBLISHED:
                raise ValueError("replacement DatasetVersion must be published")
            db.execute(
                """
                INSERT INTO dataset_versions(
                    id,dataset_id,version,status,created_at,content_sha256,payload
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    published.id, published.dataset_id, published.version,
                    published.status.value, published.created_at.isoformat(),
                    published.content_sha256, canonical_json(published),
                ),
            )
            db.execute("DELETE FROM dataset_versions WHERE id=?", (draft.id,))

    def save_run(self, run: EvaluationRun) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO runs(id,status,created_at,payload) VALUES(?,?,?,?)",
                (run.id, run.status, run.created_at.isoformat(), canonical_json(run)),
            )

    def get_run(self, run_id: str) -> EvaluationRun | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return EvaluationRun.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 50) -> list[EvaluationRun]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [EvaluationRun.model_validate_json(row[0]) for row in rows]

    def save_trace(self, trace: Trace) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO traces(id,run_id,case_id,payload) VALUES(?,?,?,?)",
                (trace.trace_id, trace.run_id, trace.case_id, canonical_json(trace)),
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

    def save_results(self, results: Sequence[EvaluationResult]) -> None:
        with self._connect() as db:
            db.executemany(
                "INSERT OR REPLACE INTO results(id,run_id,case_id,payload) VALUES(?,?,?,?)",
                [(r.id, r.run_id, r.case_id, canonical_json(r)) for r in results],
            )

    def list_results(self, run_id: str) -> list[EvaluationResult]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM results WHERE run_id=? ORDER BY case_id,id", (run_id,)
            ).fetchall()
        return [EvaluationResult.model_validate_json(row[0]) for row in rows]
