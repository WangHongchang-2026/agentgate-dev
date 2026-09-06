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
    UNIQUE(run_id, case_id),
    UNIQUE(id, run_id, case_id)
);
CREATE TABLE IF NOT EXISTS results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    evaluator_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(run_id, case_id, evaluator_id),
    FOREIGN KEY(run_id) REFERENCES runs(id),
    FOREIGN KEY(trace_id, run_id, case_id) REFERENCES traces(id, run_id, case_id)
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
                "SELECT payload FROM dataset_versions WHERE id = ?", (version.id,)
            ).fetchone()
            if existing:
                stored = DatasetVersion.model_validate_json(existing[0])
                if stored.status == DatasetVersionStatus.PUBLISHED:
                    if stored != version:
                        raise ValueError("published DatasetVersion is immutable")
                    return
                if version.status != DatasetVersionStatus.DRAFT:
                    raise ValueError(
                        "draft DatasetVersion cannot be published through save"
                    )
                if version.dataset_id != stored.dataset_id:
                    raise ValueError("DatasetVersion dataset_id is immutable")
                if version.created_at != stored.created_at:
                    raise ValueError("DatasetVersion created_at is immutable")
                if version.updated_at < stored.updated_at:
                    raise ValueError("cannot save a stale DatasetVersion draft")
                if version == stored:
                    return
                db.execute(
                    """
                    UPDATE dataset_versions
                    SET content_sha256 = ?, payload = ?
                    WHERE id = ? AND status = 'draft'
                    """,
                    (version.content_sha256, canonical_json(version), version.id),
                )
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
            if published.id == draft.id:
                raise ValueError("published DatasetVersion requires a new identity")
            if published.content_sha256 != draft.content_sha256:
                raise ValueError("published DatasetVersion content does not match the draft")
            if published.created_at != draft.created_at:
                raise ValueError("published DatasetVersion must preserve draft created_at")
            if published.based_on_version != draft.based_on_version:
                raise ValueError("published DatasetVersion must preserve draft ancestry")
            if published.updated_at < draft.updated_at:
                raise ValueError("cannot replace a newer DatasetVersion draft")
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
            existing = db.execute(
                "SELECT payload FROM runs WHERE id = ?", (run.id,)
            ).fetchone()
            if existing is None:
                db.execute(
                    "INSERT INTO runs(id,status,created_at,payload) VALUES(?,?,?,?)",
                    (run.id, run.status, run.created_at.isoformat(), canonical_json(run)),
                )
                return

            stored = EvaluationRun.model_validate_json(existing[0])
            if run == stored:
                return
            if run.manifest != stored.manifest:
                raise ValueError("EvaluationRun manifest is immutable")
            if run.created_at != stored.created_at:
                raise ValueError("EvaluationRun created_at is immutable")
            if stored.started_at is not None and run.started_at != stored.started_at:
                raise ValueError("EvaluationRun started_at is immutable once set")
            if stored.completed_at is not None:
                raise ValueError("terminal EvaluationRun is immutable")
            db.execute(
                "UPDATE runs SET status = ?, payload = ? WHERE id = ?",
                (run.status, canonical_json(run), run.id),
            )

    def get_run(self, run_id: str) -> EvaluationRun | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return EvaluationRun.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 50) -> list[EvaluationRun]:
        if limit < 1:
            raise ValueError("Run list limit must be at least 1")
        with self._connect() as db:
            rows = db.execute(
                "SELECT payload FROM runs ORDER BY created_at DESC, id LIMIT ?", (limit,)
            ).fetchall()
        return [EvaluationRun.model_validate_json(row[0]) for row in rows]

    def save_trace(self, trace: Trace) -> None:
        with self._connect() as db:
            existing = db.execute(
                "SELECT payload FROM traces WHERE id = ?", (trace.trace_id,)
            ).fetchone()
            if existing:
                stored = Trace.model_validate_json(existing[0])
                if (trace.run_id, trace.case_id) != (stored.run_id, stored.case_id):
                    raise ValueError("Trace Run and Case identity are immutable")
                if trace == stored:
                    return
                db.execute(
                    "UPDATE traces SET payload = ? WHERE id = ?",
                    (canonical_json(trace), trace.trace_id),
                )
                return

            occupied = db.execute(
                "SELECT id FROM traces WHERE run_id = ? AND case_id = ?",
                (trace.run_id, trace.case_id),
            ).fetchone()
            if occupied:
                raise ValueError("Run and Case already have a different Trace")
            db.execute(
                "INSERT INTO traces(id,run_id,case_id,payload) VALUES(?,?,?,?)",
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
                "SELECT payload FROM traces WHERE run_id=? ORDER BY case_id,id", (run_id,)
            ).fetchall()
        return [Trace.model_validate_json(row[0]) for row in rows]

    def save_results(self, results: Sequence[EvaluationResult]) -> None:
        result_items = tuple(results)
        result_ids = tuple(result.id for result in result_items)
        result_keys = tuple(
            (result.run_id, result.case_id, result.evaluator_id)
            for result in result_items
        )
        if len(set(result_ids)) != len(result_ids):
            raise ValueError("EvaluationResult ids must be unique within a batch")
        if len(set(result_keys)) != len(result_keys):
            raise ValueError(
                "EvaluationResults must be unique by Run, Case, and Evaluator"
            )

        with self._connect() as db:
            for result in result_items:
                existing = db.execute(
                    "SELECT payload FROM results WHERE id = ?", (result.id,)
                ).fetchone()
                if existing:
                    stored = EvaluationResult.model_validate_json(existing[0])
                    if stored != result:
                        raise ValueError("EvaluationResult is immutable")
                    continue

                occupied = db.execute(
                    """
                    SELECT id FROM results
                    WHERE run_id = ? AND case_id = ? AND evaluator_id = ?
                    """,
                    (result.run_id, result.case_id, result.evaluator_id),
                ).fetchone()
                if occupied:
                    raise ValueError(
                        "Run, Case, and Evaluator already have an EvaluationResult"
                    )
                db.execute(
                    """
                    INSERT INTO results(
                        id,run_id,case_id,trace_id,evaluator_id,payload
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (
                        result.id,
                        result.run_id,
                        result.case_id,
                        result.trace_id,
                        result.evaluator_id,
                        canonical_json(result),
                    ),
                )

    def list_results(self, run_id: str) -> list[EvaluationResult]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT payload FROM results
                WHERE run_id=? ORDER BY case_id,evaluator_id,id
                """,
                (run_id,),
            ).fetchall()
        return [EvaluationResult.model_validate_json(row[0]) for row in rows]
