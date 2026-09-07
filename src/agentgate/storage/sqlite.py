from __future__ import annotations

import base64
import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentgate.domain import (
    Dataset, DatasetVersion, DatasetVersionStatus, Result, Run, Trace, canonical_json,
    content_sha256,
)
from agentgate.trace.models import (
    IngestionReport, NormalizedSignal, NormalizedSpan, TraceBatch,
)
from agentgate.trace.service import TraceIngestionService
from agentgate.storage.base import (
    DatasetDraftConflictError,
    DatasetIdempotencyConflictError,
    DatasetMutationReceipt,
    PendingTraceCorrelation,
)


class SQLiteRepository:
    """SQLite JSON-document adapter behind a PostgreSQL-compatible domain boundary."""

    def __init__(self, path: str | Path = "agentgate.db") -> None:
        self.path = str(path)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            tables = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "traces" in tables and "trace_records" not in tables:
                raise RuntimeError(
                    "unsupported P1 Trace schema; back up and reset the SQLite database"
                )
            if "agentgate_schema" in tables:
                row = db.execute(
                    "SELECT version FROM agentgate_schema WHERE component='trace'"
                ).fetchone()
                if row is not None and row[0] != 3:
                    raise RuntimeError(
                        "unsupported P1 Trace schema; back up and reset the SQLite database"
                    )
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS agentgate_schema (
                    component TEXT PRIMARY KEY, version INTEGER NOT NULL
                );
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
                CREATE TABLE IF NOT EXISTS dataset_mutation_idempotency (
                    dataset_id TEXT NOT NULL REFERENCES datasets(id),
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    receipt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(dataset_id,idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_dataset_mutation_created
                    ON dataset_mutation_idempotency(dataset_id,created_at DESC);
                CREATE TABLE IF NOT EXISTS service_secrets (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
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
                CREATE TABLE IF NOT EXISTS pending_trace_correlation (
                    trace_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    invocation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pending_run
                    ON pending_trace_correlation(run_id);
                CREATE TABLE IF NOT EXISTS trace_batches (
                    id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL, received_at TEXT NOT NULL,
                    accepted_count INTEGER NOT NULL, duplicate_count INTEGER NOT NULL,
                    rejected_count INTEGER NOT NULL, conflict_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trace_spans (
                    run_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    source_trace_id TEXT NOT NULL, source_span_id TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL, payload TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    PRIMARY KEY(run_id,case_id,source_trace_id,source_span_id)
                );
                CREATE TABLE IF NOT EXISTS trace_conflicts (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    run_id TEXT, case_id TEXT,
                    source_trace_id TEXT, source_span_id TEXT,
                    original_sha256 TEXT NOT NULL, conflicting_sha256 TEXT NOT NULL,
                    received_at TEXT NOT NULL, summary TEXT NOT NULL,
                    UNIQUE(kind,run_id,case_id,source_trace_id,source_span_id,conflicting_sha256)
                );
                CREATE TABLE IF NOT EXISTS trace_signals (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    source_trace_id TEXT NOT NULL, source_span_id TEXT NOT NULL,
                    kind TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL, received_at TEXT NOT NULL,
                    UNIQUE(run_id,case_id,source_trace_id,source_span_id,kind)
                );
                CREATE TABLE IF NOT EXISTS trace_records (
                    id TEXT NOT NULL, run_id TEXT NOT NULL, case_id TEXT NOT NULL,
                    status TEXT NOT NULL, revision INTEGER NOT NULL,
                    content_sha256 TEXT NOT NULL, completed_at TEXT, updated_at TEXT NOT NULL,
                    last_evidence_at TEXT, evaluated INTEGER NOT NULL DEFAULT 0,
                    supersedes_revision INTEGER, late_arrival INTEGER NOT NULL DEFAULT 0,
                    canonical_payload TEXT NOT NULL,
                    PRIMARY KEY(run_id,case_id,revision),
                    UNIQUE(run_id,case_id,content_sha256)
                );
                CREATE INDEX IF NOT EXISTS idx_trace_spans_case
                    ON trace_spans(run_id,case_id);
                CREATE INDEX IF NOT EXISTS idx_trace_records_latest
                    ON trace_records(run_id,case_id,revision DESC);
                CREATE INDEX IF NOT EXISTS idx_trace_signals_case
                    ON trace_signals(run_id,case_id);
                INSERT INTO agentgate_schema(component,version) VALUES('trace',3)
                    ON CONFLICT(component) DO UPDATE SET version=excluded.version;
                """
            )

    @staticmethod
    def _json(model: Any) -> str:
        return canonical_json(model)

    def save_dataset(self, dataset: Dataset) -> None:
        with self._connect() as db:
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

    def save_dataset_with_draft(
        self, dataset: Dataset, draft: DatasetVersion
    ) -> None:
        if draft.dataset_id != dataset.id:
            raise ValueError("draft must belong to Dataset")
        if draft.status != DatasetVersionStatus.DRAFT:
            raise ValueError("initial DatasetVersion must be a draft")
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO datasets(id,name,archived,updated_at,payload)
                VALUES(?,?,?,?,?)
                """,
                (
                    dataset.id, dataset.name, int(dataset.archived),
                    dataset.updated_at.isoformat(), self._json(dataset),
                ),
            )
            db.execute(
                """
                INSERT INTO dataset_versions(
                    id,dataset_id,version,status,created_at,content_sha256,payload
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    draft.id, draft.dataset_id, draft.version, draft.status.value,
                    draft.created_at.isoformat(), draft.content_sha256, self._json(draft),
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
                    version.created_at.isoformat(), version.content_sha256, self._json(version),
                ),
            )

    def append_generated_cases_if_current(
        self,
        dataset_id: str,
        expected_draft_id: str,
        expected_content_sha256: str,
        updated: DatasetVersion,
        inserted_case_ids: tuple[str, ...],
        idempotency_key: str,
        request_sha256: str,
    ) -> DatasetMutationReceipt:
        if not idempotency_key.strip():
            raise ValueError("Idempotency-Key is required")
        if updated.id != expected_draft_id or updated.dataset_id != dataset_id:
            raise ValueError("updated draft identity mismatch")
        if updated.status != DatasetVersionStatus.DRAFT:
            raise ValueError("updated DatasetVersion must remain a draft")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            replay = db.execute(
                """SELECT request_sha256,receipt FROM dataset_mutation_idempotency
                   WHERE dataset_id=? AND idempotency_key=?""",
                (dataset_id, idempotency_key),
            ).fetchone()
            if replay is not None:
                if replay["request_sha256"] != request_sha256:
                    raise DatasetIdempotencyConflictError(
                        "Idempotency-Key was already used for a different request"
                    )
                payload = json.loads(replay["receipt"])
                return DatasetMutationReceipt(
                    draft_id=payload["draft_id"],
                    content_sha256=payload["content_sha256"],
                    inserted_case_ids=tuple(payload["inserted_case_ids"]),
                )
            cursor = db.execute(
                """UPDATE dataset_versions
                   SET content_sha256=?,payload=?
                   WHERE dataset_id=? AND id=? AND status='draft' AND content_sha256=?""",
                (
                    updated.content_sha256,
                    self._json(updated),
                    dataset_id,
                    expected_draft_id,
                    expected_content_sha256,
                ),
            )
            if cursor.rowcount != 1:
                raise DatasetDraftConflictError("dataset draft changed; refresh and try again")
            receipt = DatasetMutationReceipt(
                draft_id=updated.id,
                content_sha256=updated.content_sha256,
                inserted_case_ids=inserted_case_ids,
            )
            receipt_payload = {
                "draft_id": receipt.draft_id,
                "content_sha256": receipt.content_sha256,
                "inserted_case_ids": list(receipt.inserted_case_ids),
            }
            db.execute(
                """INSERT INTO dataset_mutation_idempotency(
                       dataset_id,idempotency_key,request_sha256,receipt,created_at
                   ) VALUES(?,?,?,?,?)""",
                (
                    dataset_id,
                    idempotency_key,
                    request_sha256,
                    canonical_json(receipt_payload),
                    datetime.now(UTC).isoformat(),
                ),
            )
            db.execute(
                """DELETE FROM dataset_mutation_idempotency
                   WHERE dataset_id=? AND rowid NOT IN (
                       SELECT rowid FROM dataset_mutation_idempotency
                       WHERE dataset_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1000
                   )""",
                (dataset_id, dataset_id),
            )
            return receipt

    def get_dataset_mutation_receipt(
        self, dataset_id: str, idempotency_key: str, request_sha256: str
    ) -> DatasetMutationReceipt | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT request_sha256,receipt FROM dataset_mutation_idempotency
                   WHERE dataset_id=? AND idempotency_key=?""",
                (dataset_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise DatasetIdempotencyConflictError(
                "Idempotency-Key was already used for a different request"
            )
        payload = json.loads(row["receipt"])
        return DatasetMutationReceipt(
            draft_id=payload["draft_id"],
            content_sha256=payload["content_sha256"],
            inserted_case_ids=tuple(payload["inserted_case_ids"]),
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

    @staticmethod
    def _case_for_run(run: Run, case_id: str):
        return next((item for item in run.snapshot.dataset.cases if item.id == case_id), None)

    def _record_conflict(
        self, db: sqlite3.Connection, *, kind: str, run_id: str | None,
        case_id: str | None, source_trace_id: str | None,
        source_span_id: str | None, original_sha256: str = "",
        conflicting_sha256: str = "", received_at: str, summary: str,
    ) -> bool:
        # SQLite UNIQUE constraints treat NULL values as distinct. Normalize the
        # optional correlation coordinates so rebuilding the same canonical
        # trace cannot create duplicate conflict rows.
        run_id = run_id or ""
        case_id = case_id or ""
        source_trace_id = source_trace_id or ""
        source_span_id = source_span_id or ""
        cursor = db.execute(
            """
            INSERT OR IGNORE INTO trace_conflicts(
                id,kind,run_id,case_id,source_trace_id,source_span_id,
                original_sha256,conflicting_sha256,received_at,summary
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(uuid4()), kind, run_id, case_id, source_trace_id, source_span_id,
                original_sha256, conflicting_sha256, received_at, summary[:500],
            ),
        )
        return bool(cursor.rowcount)

    def _rebuild_trace(
        self, db: sqlite3.Connection, run: Run, case_id: str, *, now: datetime,
        deadline_elapsed: bool = False, late_arrival: bool = False,
    ) -> Trace:
        case = self._case_for_run(run, case_id)
        if case is None:
            raise ValueError(f"case {case_id} is not in run")
        spans = [NormalizedSpan.model_validate_json(row[0]) for row in db.execute(
            "SELECT payload FROM trace_spans WHERE run_id=? AND case_id=?",
            (run.id, case_id),
        ).fetchall()]
        signals = [NormalizedSignal.model_validate_json(row[0]) for row in db.execute(
            "SELECT payload FROM trace_signals WHERE run_id=? AND case_id=?",
            (run.id, case_id),
        ).fetchall()]
        latest_row = db.execute(
            """SELECT revision,content_sha256,canonical_payload,last_evidence_at
               FROM trace_records WHERE run_id=? AND case_id=?
               ORDER BY revision DESC LIMIT 1""",
            (run.id, case_id),
        ).fetchone()
        latest_revision = latest_row[0] if latest_row else 0
        evidence_times = [row[0] for row in db.execute(
            """SELECT received_at FROM trace_spans WHERE run_id=? AND case_id=?
               UNION ALL SELECT received_at FROM trace_signals WHERE run_id=? AND case_id=?""",
            (run.id, case_id, run.id, case_id),
        ).fetchall()]
        last_evidence_at = max(datetime.fromisoformat(value) for value in evidence_times) \
            if evidence_times else None

        persisted_conflict_count = db.execute(
            "SELECT COUNT(*) FROM trace_conflicts WHERE run_id=? AND case_id=?",
            (run.id, case_id),
        ).fetchone()[0]
        persisted_conflict_keys = {
            (row[0], row[1], row[2]) for row in db.execute(
                """SELECT kind,original_sha256,conflicting_sha256
                   FROM trace_conflicts WHERE run_id=? AND case_id=?""",
                (run.id, case_id),
            ).fetchall()
        }
        trace, discovered = TraceIngestionService.reconstruct(
            run, case, spans, signals,
            persisted_conflict_count=persisted_conflict_count,
            persisted_conflict_keys=persisted_conflict_keys,
            revision=latest_revision + 1,
            last_evidence_at=last_evidence_at, now=now,
            deadline_elapsed=deadline_elapsed,
        )
        for conflict in discovered:
            self._record_conflict(
                db, kind=conflict.kind, run_id=conflict.run_id,
                case_id=conflict.case_id,
                source_trace_id=conflict.source_trace_id,
                source_span_id=conflict.source_span_id,
                original_sha256=conflict.original_sha256,
                conflicting_sha256=conflict.conflicting_sha256,
                received_at=conflict.received_at.isoformat(),
                summary=conflict.summary,
            )
        if not TraceIngestionService.should_create_revision(
            latest_row[1] if latest_row else None, trace.content_sha256
        ):
            return Trace.model_validate_json(latest_row[2])
        db.execute(
            """
            INSERT INTO trace_records(
                id,run_id,case_id,status,revision,content_sha256,completed_at,
                updated_at,last_evidence_at,evaluated,supersedes_revision,
                late_arrival,canonical_payload
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trace.id, run.id, case_id, trace.status.value, trace.revision,
                trace.content_sha256,
                trace.completed_at.isoformat() if trace.completed_at else None,
                now.isoformat(), last_evidence_at.isoformat() if last_evidence_at else None,
                0, latest_revision or None, int(late_arrival), self._json(trace),
            ),
        )
        db.execute(
            """INSERT INTO traces(id,run_id,case_id,payload) VALUES(?,?,?,?)
               ON CONFLICT(run_id,case_id) DO UPDATE SET
                   id=excluded.id,payload=excluded.payload""",
            (trace.id, run.id, case_id, self._json(trace)),
        )
        return trace

    def ingest_trace_batch(self, batch: TraceBatch) -> IngestionReport:
        """Atomically persist normalized evidence and rebuild affected traces."""
        accepted = duplicates = span_conflicts = 0
        accepted_signals = duplicate_signals = signal_conflicts = 0
        rejected = batch.rejected_spans
        errors = list(batch.errors)
        affected: set[tuple[str, str]] = set()
        changed: set[tuple[str, str]] = set()
        with self._connect() as db:
            evidence_keys = {
                (item.run_id, item.case_id) for item in (*batch.spans, *batch.signals)
            }
            rejected_keys: set[tuple[str, str]] = set()
            late_keys: set[tuple[str, str]] = set()
            for key in evidence_keys:
                run = self.get_run(key[0])
                latest_evaluated = db.execute(
                    """SELECT 1 FROM trace_records WHERE run_id=? AND case_id=?
                       AND evaluated=1 LIMIT 1""", key,
                ).fetchone()
                late_disposition = (
                    TraceIngestionService.classify_late_arrival(
                        run, bool(latest_evaluated)
                    ) if run else "normal"
                )
                if late_disposition == "reject":
                    rejected_keys.add(key)
                    errors.append(f"late telemetry rejected for {key[0]}:{key[1]}")
                elif late_disposition == "late_revision":
                    late_keys.add(key)

            for conflict in batch.conflicts:
                if self._record_conflict(
                    db, kind=conflict.kind, run_id=conflict.run_id,
                    case_id=conflict.case_id, source_trace_id=conflict.source_trace_id,
                    source_span_id=conflict.source_span_id,
                    original_sha256=conflict.original_sha256,
                    conflicting_sha256=conflict.conflicting_sha256,
                    received_at=batch.received_at.isoformat(), summary=conflict.summary,
                ) and conflict.run_id and conflict.case_id:
                    changed.add((conflict.run_id, conflict.case_id))

            for span in batch.spans:
                key = (span.run_id, span.case_id)
                affected.add(key)
                if key in rejected_keys:
                    rejected += 1
                    continue
                identity = (span.run_id, span.case_id, span.source_trace_id, span.source_span_id)
                span_hash = content_sha256(span)
                existing = db.execute(
                    """SELECT content_sha256 FROM trace_spans WHERE run_id=? AND case_id=?
                       AND source_trace_id=? AND source_span_id=?""", identity,
                ).fetchone()
                disposition = TraceIngestionService.classify_content(
                    existing[0] if existing else None, span_hash
                )
                if disposition == "new":
                    db.execute(
                        """INSERT INTO trace_spans(run_id,case_id,source_trace_id,
                           source_span_id,content_sha256,payload,received_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (*identity, span_hash, self._json(span), batch.received_at.isoformat()),
                    )
                    accepted += 1
                    changed.add(key)
                elif disposition == "duplicate":
                    duplicates += 1
                elif self._record_conflict(
                    db, kind="span_content", run_id=span.run_id, case_id=span.case_id,
                    source_trace_id=span.source_trace_id, source_span_id=span.source_span_id,
                    original_sha256=existing[0], conflicting_sha256=span_hash,
                    received_at=batch.received_at.isoformat(),
                    summary="span identity/content conflict",
                ):
                    span_conflicts += 1
                    changed.add(key)
                else:
                    duplicates += 1

            for signal in batch.signals:
                key = (signal.run_id, signal.case_id)
                affected.add(key)
                if key in rejected_keys:
                    continue
                identity = (
                    signal.run_id, signal.case_id, signal.source_trace_id,
                    signal.source_span_id, signal.kind,
                )
                existing = db.execute(
                    """SELECT content_sha256 FROM trace_signals WHERE run_id=? AND case_id=?
                       AND source_trace_id=? AND source_span_id=? AND kind=?""", identity,
                ).fetchone()
                disposition = TraceIngestionService.classify_content(
                    existing[0] if existing else None, signal.content_sha256
                )
                if disposition == "new":
                    db.execute(
                        """INSERT INTO trace_signals(id,run_id,case_id,source_trace_id,
                           source_span_id,kind,content_sha256,payload,received_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (
                            signal.id, *identity, signal.content_sha256,
                            self._json(signal), batch.received_at.isoformat(),
                        ),
                    )
                    accepted_signals += 1
                    changed.add(key)
                elif disposition == "duplicate":
                    duplicate_signals += 1
                elif self._record_conflict(
                    db, kind="semantic_signal", run_id=signal.run_id,
                    case_id=signal.case_id, source_trace_id=signal.source_trace_id,
                    source_span_id=signal.source_span_id, original_sha256=existing[0],
                    conflicting_sha256=signal.content_sha256,
                    received_at=batch.received_at.isoformat(),
                    summary=f"{signal.kind} identity/content conflict",
                ):
                    signal_conflicts += 1
                    changed.add(key)
                else:
                    duplicate_signals += 1

            for run_id, case_id in sorted(changed):
                run = self.get_run(run_id)
                if run is not None and self._case_for_run(run, case_id) is not None:
                    self._rebuild_trace(
                        db, run, case_id, now=batch.received_at,
                        late_arrival=(run_id, case_id) in late_keys,
                    )
            db.execute(
                """INSERT OR IGNORE INTO trace_batches(id,content_sha256,source,received_at,
                   accepted_count,duplicate_count,rejected_count,conflict_count)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (
                    batch.id, batch.content_sha256, batch.source,
                    batch.received_at.isoformat(), accepted, duplicates, rejected,
                    span_conflicts + signal_conflicts,
                ),
            )
        return IngestionReport(
            accepted_spans=accepted, duplicate_spans=duplicates,
            rejected_spans=rejected, conflicted_spans=span_conflicts,
            accepted_signals=accepted_signals, duplicate_signals=duplicate_signals,
            conflicted_signals=signal_conflicts,
            affected_traces=tuple(f"{a}:{b}" for a, b in sorted(affected)),
            errors=tuple(errors[:20]),
        )

    def get_trace_revision(
        self, run_id: str, case_id: str, revision: int
    ) -> Trace | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT canonical_payload FROM trace_records
                   WHERE run_id=? AND case_id=? AND revision=?""",
                (run_id, case_id, revision),
            ).fetchone()
        return Trace.model_validate_json(row[0]) if row else None

    def evaluate_trace_completeness(
        self, run_id: str, case_id: str, now: datetime
    ) -> Trace:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run {run_id}")
        with self._connect() as db:
            return self._rebuild_trace(db, run, case_id, now=now)

    def expire_trace(self, run_id: str, case_id: str, now: datetime) -> Trace:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError(f"unknown run {run_id}")
        started = run.started_at or run.snapshot.created_at
        deadline = started.timestamp() + run.snapshot.trace_policy.deadline_seconds
        if now.timestamp() < deadline:
            current = self.get_trace(run_id, case_id)
            if current is None:
                raise ValueError("trace has no accepted evidence")
            return current
        with self._connect() as db:
            return self._rebuild_trace(
                db, run, case_id, now=now, deadline_elapsed=True
            )

    def expire_due_traces(self, now: datetime, limit: int = 100) -> tuple[Trace, ...]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT r.run_id,r.case_id FROM trace_records r
                JOIN (
                    SELECT run_id,case_id,MAX(revision) revision FROM trace_records
                    GROUP BY run_id,case_id
                ) latest USING(run_id,case_id,revision)
                WHERE r.status='collecting' ORDER BY r.updated_at LIMIT ?
                """,
                (limit,),
            ).fetchall()
        expired = []
        for row in rows:
            run = self.get_run(row[0])
            if run is None:
                continue
            started = run.started_at or run.snapshot.created_at
            if now.timestamp() >= started.timestamp() + run.snapshot.trace_policy.deadline_seconds:
                expired.append(self.expire_trace(row[0], row[1], now))
        return tuple(expired)

    def get_latest_evaluated_trace(self, run_id: str, case_id: str) -> Trace | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT canonical_payload FROM trace_records
                   WHERE run_id=? AND case_id=? AND evaluated=1
                   ORDER BY revision DESC LIMIT 1""",
                (run_id, case_id),
            ).fetchone()
        return Trace.model_validate_json(row[0]) if row else None

    def has_unevaluated_trace_revision(self, run_id: str, case_id: str) -> bool:
        with self._connect() as db:
            return db.execute(
                """SELECT 1 FROM trace_records WHERE run_id=? AND case_id=?
                   AND evaluated=0 LIMIT 1""",
                (run_id, case_id),
            ).fetchone() is not None

    def get_trace_revision_metadata(
        self, run_id: str, case_id: str, revision: int
    ) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT status,content_sha256,evaluated,supersedes_revision,
                          late_arrival,last_evidence_at,updated_at
                   FROM trace_records WHERE run_id=? AND case_id=? AND revision=?""",
                (run_id, case_id, revision),
            ).fetchone()
        return dict(row) if row else None

    def list_trace_conflicts(
        self, run_id: str, case_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self._connect() as db:
            rows = db.execute(
                """SELECT kind,source_trace_id,source_span_id,original_sha256,
                          conflicting_sha256,received_at,summary
                   FROM trace_conflicts WHERE run_id=? AND case_id=?
                   ORDER BY received_at,id LIMIT ?""",
                (run_id, case_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_results(self, results: list[Result]) -> None:
        with self._connect() as db:
            db.executemany(
                "INSERT OR REPLACE INTO results(id,run_id,case_id,payload) VALUES(?,?,?,?)",
                [(r.id, r.run_id, r.case_id, self._json(r)) for r in results],
            )
            for result in results:
                if result.trace_revision is not None and result.trace_content_sha256:
                    db.execute(
                        """UPDATE trace_records SET evaluated=1
                           WHERE run_id=? AND case_id=? AND revision=?
                           AND content_sha256=?""",
                        (
                            result.run_id, result.case_id, result.trace_revision,
                            result.trace_content_sha256,
                        ),
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

    def get_or_create_service_secret(self, name: str, byte_length: int = 32) -> bytes:
        if not name.strip():
            raise ValueError("service secret name must be non-empty")
        if byte_length < 32:
            raise ValueError("service secrets must contain at least 32 bytes")
        candidate = base64.urlsafe_b64encode(secrets.token_bytes(byte_length)).decode("ascii")
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO service_secrets(name,value,created_at) VALUES(?,?,?)",
                (name, candidate, datetime.now(UTC).isoformat()),
            )
            row = db.execute(
                "SELECT value FROM service_secrets WHERE name=?", (name,)
            ).fetchone()
        if row is None:  # Defensive: INSERT/SELECT above must be atomic in one transaction.
            raise RuntimeError("failed to initialize service secret")
        return base64.urlsafe_b64decode(row[0].encode("ascii"))

    def put_pending_trace(
        self, run_id: str, case_id: str, invocation_id: str, trace_id: str
    ) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT OR REPLACE INTO pending_trace_correlation(
                   trace_id,run_id,case_id,invocation_id,created_at) VALUES(?,?,?,?,?)""",
                (trace_id, run_id, case_id, invocation_id, datetime.now(UTC).isoformat()),
            )

    def get_pending_trace(self, trace_id: str) -> PendingTraceCorrelation | None:
        with self._connect() as db:
            row = db.execute(
                """SELECT trace_id,run_id,case_id,invocation_id,created_at
                   FROM pending_trace_correlation WHERE trace_id=?""",
                (trace_id,),
            ).fetchone()
        return PendingTraceCorrelation(
            run_id=row["run_id"], case_id=row["case_id"],
            invocation_id=row["invocation_id"], trace_id=row["trace_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        ) if row else None
