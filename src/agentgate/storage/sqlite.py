from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from agentgate.domain import (
    Dataset,
    DatasetVersion,
    DatasetVersionStatus,
    EvaluationResult,
    EvaluationRun,
    Evaluator,
    EvaluatorDraft,
    EvaluatorSource,
    EvaluatorSpec,
    RunStatus,
    SkillAnalysisReport,
    SkillAnalysisReview,
    TargetDescriptor,
    TargetRef,
    TargetType,
    Trace,
    canonical_json,
    content_sha256,
    transition_run,
)
from agentgate.evaluator.versioning import (
    publish_evaluator_draft as build_evaluator_publication,
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS target_descriptors (
    content_sha256 TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('agent', 'skill')),
    external_target_id TEXT NOT NULL,
    external_version_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_target_descriptor_ref
    ON target_descriptors(
        source_id,
        target_type,
        external_target_id,
        external_version_id
    );
CREATE TABLE IF NOT EXISTS skill_analysis_reports (
    id TEXT PRIMARY KEY,
    target_descriptor_sha256 TEXT NOT NULL
        REFERENCES target_descriptors(content_sha256),
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_analysis_reports_target
    ON skill_analysis_reports(
        target_descriptor_sha256,
        created_at DESC,
        id
    );
CREATE TABLE IF NOT EXISTS skill_analysis_reviews (
    report_id TEXT NOT NULL
        REFERENCES skill_analysis_reports(id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY(report_id, finding_id)
);
CREATE TABLE IF NOT EXISTS evaluators (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK(source = 'user'),
    enabled INTEGER NOT NULL CHECK(enabled IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evaluators_enabled_updated
    ON evaluators(enabled, updated_at DESC, id);
CREATE TABLE IF NOT EXISTS evaluator_drafts (
    id TEXT PRIMARY KEY,
    evaluator_id TEXT NOT NULL UNIQUE
        REFERENCES evaluators(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluator_versions (
    evaluator_id TEXT NOT NULL REFERENCES evaluators(id),
    version INTEGER NOT NULL CHECK(version >= 1),
    content_sha256 TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY(evaluator_id, version)
);
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
CREATE INDEX IF NOT EXISTS idx_runs_status_created
    ON runs(status, created_at, id);
CREATE TABLE IF NOT EXISTS run_asset_refs (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    asset_kind TEXT NOT NULL CHECK(
        asset_kind IN ('dataset', 'case', 'agent', 'skill', 'evaluator')
    ),
    source_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    version TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    PRIMARY KEY(
        run_id,
        asset_kind,
        source_id,
        asset_id,
        version,
        content_sha256
    )
);
CREATE INDEX IF NOT EXISTS idx_run_asset_lookup
    ON run_asset_refs(
        asset_kind,
        source_id,
        asset_id,
        version,
        content_sha256,
        run_id
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

    def save_target_descriptor(self, descriptor: TargetDescriptor) -> None:
        with self._connect() as db:
            existing = db.execute(
                "SELECT payload FROM target_descriptors WHERE content_sha256 = ?",
                (descriptor.content_sha256,),
            ).fetchone()
            if existing is not None:
                stored = TargetDescriptor.model_validate_json(existing[0])
                stored_content = stored.model_dump(
                    mode="json", exclude={"fetched_at"}
                )
                incoming_content = descriptor.model_dump(
                    mode="json", exclude={"fetched_at"}
                )
                if stored_content != incoming_content:
                    raise ValueError("TargetDescriptor content hash collision")
                return
            db.execute(
                """
                INSERT INTO target_descriptors(
                    content_sha256,
                    source_id,
                    target_type,
                    external_target_id,
                    external_version_id,
                    fetched_at,
                    payload
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    descriptor.content_sha256,
                    descriptor.ref.source_id,
                    descriptor.ref.target_type.value,
                    descriptor.ref.external_target_id,
                    descriptor.ref.external_version_id,
                    descriptor.fetched_at.isoformat(),
                    canonical_json(descriptor),
                ),
            )

    def get_target_descriptor(
        self, content_sha256: str
    ) -> TargetDescriptor | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM target_descriptors WHERE content_sha256 = ?",
                (content_sha256,),
            ).fetchone()
        return TargetDescriptor.model_validate_json(row[0]) if row else None

    def list_target_descriptors(
        self, ref: TargetRef | None = None
    ) -> list[TargetDescriptor]:
        query = "SELECT payload FROM target_descriptors"
        parameters: tuple[object, ...] = ()
        if ref is not None:
            query += (
                " WHERE source_id=? AND target_type=?"
                " AND external_target_id=? AND external_version_id=?"
            )
            parameters = (
                ref.source_id,
                ref.target_type.value,
                ref.external_target_id,
                ref.external_version_id,
            )
        query += " ORDER BY fetched_at DESC, content_sha256"
        with self._connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [TargetDescriptor.model_validate_json(row[0]) for row in rows]

    def save_skill_analysis_report(self, report: SkillAnalysisReport) -> None:
        with self._connect() as db:
            existing = db.execute(
                "SELECT payload FROM skill_analysis_reports WHERE id=?",
                (report.id,),
            ).fetchone()
            if existing is not None:
                stored = SkillAnalysisReport.model_validate_json(existing[0])
                if stored != report:
                    raise ValueError("SkillAnalysisReport is immutable")
                return
            db.execute(
                """
                INSERT INTO skill_analysis_reports(
                    id,
                    target_descriptor_sha256,
                    content_sha256,
                    created_at,
                    payload
                ) VALUES(?,?,?,?,?)
                """,
                (
                    report.id,
                    report.target_descriptor_sha256,
                    report.content_sha256,
                    report.created_at.isoformat(),
                    canonical_json(report),
                ),
            )

    def get_skill_analysis_report(
        self, report_id: str
    ) -> SkillAnalysisReport | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM skill_analysis_reports WHERE id=?",
                (report_id,),
            ).fetchone()
        return SkillAnalysisReport.model_validate_json(row[0]) if row else None

    def list_skill_analysis_reports(
        self, target_descriptor_sha256: str, limit: int = 50
    ) -> list[SkillAnalysisReport]:
        if limit < 1:
            raise ValueError("SkillAnalysisReport list limit must be at least 1")
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT payload FROM skill_analysis_reports
                WHERE target_descriptor_sha256=?
                ORDER BY created_at DESC,id
                LIMIT ?
                """,
                (target_descriptor_sha256, limit),
            ).fetchall()
        return [SkillAnalysisReport.model_validate_json(row[0]) for row in rows]

    def save_skill_analysis_review(
        self, report_id: str, review: SkillAnalysisReview
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO skill_analysis_reviews(
                    report_id,finding_id,reviewed_at,payload
                ) VALUES(?,?,?,?)
                ON CONFLICT(report_id,finding_id) DO UPDATE SET
                    reviewed_at=excluded.reviewed_at,
                    payload=excluded.payload
                """,
                (
                    report_id,
                    review.finding_id,
                    review.reviewed_at.isoformat(),
                    canonical_json(review),
                ),
            )

    def list_skill_analysis_reviews(
        self, report_id: str
    ) -> list[SkillAnalysisReview]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT payload FROM skill_analysis_reviews
                WHERE report_id=? ORDER BY finding_id
                """,
                (report_id,),
            ).fetchall()
        return [SkillAnalysisReview.model_validate_json(row[0]) for row in rows]

    def save_evaluator(self, evaluator: Evaluator) -> None:
        _require_user_evaluator(evaluator)
        with self._connect() as db:
            existing = db.execute(
                "SELECT payload FROM evaluators WHERE id=?", (evaluator.id,)
            ).fetchone()
            if existing is not None:
                stored = Evaluator.model_validate_json(existing[0])
                if evaluator.source != stored.source:
                    raise ValueError("Evaluator source is immutable")
                if evaluator.created_at != stored.created_at:
                    raise ValueError("Evaluator created_at is immutable")
                if evaluator.updated_at < stored.updated_at:
                    raise ValueError("cannot save a stale Evaluator")
                if evaluator == stored:
                    return
            db.execute(
                """
                INSERT INTO evaluators(
                    id,source,enabled,created_at,updated_at,payload
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """,
                (
                    evaluator.id,
                    evaluator.source.value,
                    int(evaluator.enabled),
                    evaluator.created_at.isoformat(),
                    evaluator.updated_at.isoformat(),
                    canonical_json(evaluator),
                ),
            )

    def save_evaluator_with_draft(
        self,
        evaluator: Evaluator,
        draft: EvaluatorDraft,
    ) -> None:
        _require_user_evaluator(evaluator)
        if draft.evaluator_id != evaluator.id:
            raise ValueError("EvaluatorDraft must belong to Evaluator")
        if draft.created_at < evaluator.created_at:
            raise ValueError("EvaluatorDraft cannot precede Evaluator creation")
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO evaluators(
                    id,source,enabled,created_at,updated_at,payload
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    evaluator.id,
                    evaluator.source.value,
                    int(evaluator.enabled),
                    evaluator.created_at.isoformat(),
                    evaluator.updated_at.isoformat(),
                    canonical_json(evaluator),
                ),
            )
            db.execute(
                """
                INSERT INTO evaluator_drafts(
                    id,evaluator_id,created_at,updated_at,payload
                ) VALUES(?,?,?,?,?)
                """,
                (
                    draft.id,
                    draft.evaluator_id,
                    draft.created_at.isoformat(),
                    draft.updated_at.isoformat(),
                    canonical_json(draft),
                ),
            )

    def get_evaluator(self, evaluator_id: str) -> Evaluator | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM evaluators WHERE id=?", (evaluator_id,)
            ).fetchone()
        return Evaluator.model_validate_json(row[0]) if row else None

    def list_evaluators(
        self,
        include_disabled: bool = False,
    ) -> list[Evaluator]:
        query = "SELECT payload FROM evaluators"
        if not include_disabled:
            query += " WHERE enabled=1"
        query += " ORDER BY updated_at DESC, id"
        with self._connect() as db:
            rows = db.execute(query).fetchall()
        return [Evaluator.model_validate_json(row[0]) for row in rows]

    def delete_unpublished_evaluator(self, evaluator_id: str) -> None:
        with self._connect() as db:
            evaluator = db.execute(
                "SELECT 1 FROM evaluators WHERE id=?", (evaluator_id,)
            ).fetchone()
            if evaluator is None:
                raise ValueError(f"unknown Evaluator: {evaluator_id}")
            publication = db.execute(
                "SELECT 1 FROM evaluator_versions WHERE evaluator_id=? LIMIT 1",
                (evaluator_id,),
            ).fetchone()
            if publication is not None:
                raise ValueError("published Evaluator cannot be deleted")
            db.execute("DELETE FROM evaluators WHERE id=?", (evaluator_id,))

    def save_evaluator_draft(self, draft: EvaluatorDraft) -> None:
        with self._connect() as db:
            evaluator_row = db.execute(
                "SELECT payload FROM evaluators WHERE id=?",
                (draft.evaluator_id,),
            ).fetchone()
            if evaluator_row is None:
                raise ValueError(f"unknown Evaluator: {draft.evaluator_id}")
            evaluator = Evaluator.model_validate_json(evaluator_row[0])
            if draft.created_at < evaluator.created_at:
                raise ValueError("EvaluatorDraft cannot precede Evaluator creation")

            existing = db.execute(
                "SELECT payload FROM evaluator_drafts WHERE id=?", (draft.id,)
            ).fetchone()
            if existing is not None:
                stored = EvaluatorDraft.model_validate_json(existing[0])
                if draft.evaluator_id != stored.evaluator_id:
                    raise ValueError("EvaluatorDraft evaluator_id is immutable")
                if draft.created_at != stored.created_at:
                    raise ValueError("EvaluatorDraft created_at is immutable")
                if draft.based_on_version != stored.based_on_version:
                    raise ValueError("EvaluatorDraft based_on_version is immutable")
                if draft.updated_at < stored.updated_at:
                    raise ValueError("cannot save a stale EvaluatorDraft")
                if draft == stored:
                    return
                db.execute(
                    """
                    UPDATE evaluator_drafts
                    SET updated_at=?, payload=?
                    WHERE id=?
                    """,
                    (draft.updated_at.isoformat(), canonical_json(draft), draft.id),
                )
                return

            active = db.execute(
                "SELECT id FROM evaluator_drafts WHERE evaluator_id=?",
                (draft.evaluator_id,),
            ).fetchone()
            if active is not None:
                raise ValueError("Evaluator already has an active draft")
            db.execute(
                """
                INSERT INTO evaluator_drafts(
                    id,evaluator_id,created_at,updated_at,payload
                ) VALUES(?,?,?,?,?)
                """,
                (
                    draft.id,
                    draft.evaluator_id,
                    draft.created_at.isoformat(),
                    draft.updated_at.isoformat(),
                    canonical_json(draft),
                ),
            )

    def get_evaluator_draft(
        self,
        evaluator_id: str,
    ) -> EvaluatorDraft | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM evaluator_drafts WHERE evaluator_id=?",
                (evaluator_id,),
            ).fetchone()
        return EvaluatorDraft.model_validate_json(row[0]) if row else None

    def delete_evaluator_draft(
        self,
        evaluator_id: str,
        expected_draft_id: str,
    ) -> None:
        with self._connect() as db:
            cursor = db.execute(
                """
                DELETE FROM evaluator_drafts
                WHERE evaluator_id=? AND id=?
                """,
                (evaluator_id, expected_draft_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("expected Evaluator draft does not exist")

    def list_evaluator_versions(
        self,
        evaluator_id: str,
    ) -> list[EvaluatorSpec]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT version,content_sha256,payload
                FROM evaluator_versions
                WHERE evaluator_id=?
                ORDER BY version DESC
                """,
                (evaluator_id,),
            ).fetchall()
        return [_load_evaluator_spec(row) for row in rows]

    def get_evaluator_version(
        self,
        evaluator_id: str,
        version: str,
    ) -> EvaluatorSpec | None:
        version_number = _parse_evaluator_version(version)
        with self._connect() as db:
            row = db.execute(
                """
                SELECT version,content_sha256,payload
                FROM evaluator_versions
                WHERE evaluator_id=? AND version=?
                """,
                (evaluator_id, version_number),
            ).fetchone()
        return _load_evaluator_spec(row) if row else None

    def get_latest_evaluator_version(
        self,
        evaluator_id: str,
    ) -> EvaluatorSpec | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT version,content_sha256,payload
                FROM evaluator_versions
                WHERE evaluator_id=?
                ORDER BY version DESC
                LIMIT 1
                """,
                (evaluator_id,),
            ).fetchone()
        return _load_evaluator_spec(row) if row else None

    def publish_evaluator_draft(
        self,
        expected_draft_id: str,
        published: EvaluatorSpec,
    ) -> None:
        version = _parse_evaluator_version(published.version)
        with self._connect() as db:
            draft_row = db.execute(
                "SELECT payload FROM evaluator_drafts WHERE id=?",
                (expected_draft_id,),
            ).fetchone()
            if draft_row is None:
                raise ValueError("expected Evaluator draft does not exist")
            draft = EvaluatorDraft.model_validate_json(draft_row[0])

            evaluator_row = db.execute(
                "SELECT payload FROM evaluators WHERE id=?",
                (draft.evaluator_id,),
            ).fetchone()
            if evaluator_row is None:
                raise ValueError(f"unknown Evaluator: {draft.evaluator_id}")
            evaluator = Evaluator.model_validate_json(evaluator_row[0])

            latest_row = db.execute(
                """
                SELECT MAX(version) FROM evaluator_versions
                WHERE evaluator_id=?
                """,
                (evaluator.id,),
            ).fetchone()
            next_version = (latest_row[0] or 0) + 1
            if version != next_version:
                raise ValueError(
                    f"Evaluator publication requires version {next_version}"
                )

            expected = build_evaluator_publication(
                evaluator,
                draft,
                next_version,
            )
            if published != expected:
                raise ValueError(
                    "published EvaluatorSpec does not match the current draft"
                )

            db.execute(
                """
                INSERT INTO evaluator_versions(
                    evaluator_id,version,content_sha256,payload
                ) VALUES(?,?,?,?)
                """,
                (
                    published.id,
                    version,
                    published.content_sha256,
                    canonical_json(published),
                ),
            )
            cursor = db.execute(
                "DELETE FROM evaluator_drafts WHERE id=?",
                (expected_draft_id,),
            )
            if cursor.rowcount != 1:
                raise ValueError("expected Evaluator draft does not exist")

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

    def save_dataset_with_version(
        self, dataset: Dataset, version: DatasetVersion
    ) -> None:
        if version.dataset_id != dataset.id:
            raise ValueError("DatasetVersion must belong to Dataset")
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO datasets(id,name,archived,updated_at,payload)
                VALUES(?,?,?,?,?)
                """,
                (
                    dataset.id,
                    dataset.name,
                    int(dataset.archived),
                    dataset.updated_at.isoformat(),
                    canonical_json(dataset),
                ),
            )
            db.execute(
                """
                INSERT INTO dataset_versions(
                    id,dataset_id,version,status,created_at,content_sha256,payload
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    version.id,
                    version.dataset_id,
                    version.version,
                    version.status.value,
                    version.created_at.isoformat(),
                    version.content_sha256,
                    canonical_json(version),
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
                references = self._run_asset_references(db, run)
                db.execute(
                    "INSERT INTO runs(id,status,created_at,payload) VALUES(?,?,?,?)",
                    (run.id, run.status, run.created_at.isoformat(), canonical_json(run)),
                )
                db.executemany(
                    """
                    INSERT INTO run_asset_refs(
                        run_id,asset_kind,source_id,asset_id,version,content_sha256
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    references,
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

    def list_runs_by_dataset_version(
        self, dataset_id: str, version: int, limit: int = 50
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            "dataset", "", dataset_id, str(version), limit=limit
        )

    def list_runs_by_case_content(
        self,
        dataset_id: str,
        version: int,
        case_id: str,
        content_sha256: str,
        limit: int = 50,
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            "case",
            dataset_id,
            case_id,
            str(version),
            content_sha256=content_sha256,
            limit=limit,
        )

    def list_runs_by_target_version(
        self,
        source_id: str,
        target_type: TargetType,
        target_id: str,
        version: str,
        limit: int = 50,
        *,
        content_sha256: str | None = None,
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            target_type.value,
            source_id,
            target_id,
            version,
            content_sha256=content_sha256,
            limit=limit,
        )

    def list_runs_by_skill_version(
        self,
        source_id: str,
        skill_id: str,
        version: str,
        limit: int = 50,
        *,
        content_sha256: str | None = None,
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            "skill",
            source_id,
            skill_id,
            version,
            content_sha256=content_sha256,
            limit=limit,
        )

    def list_runs_by_evaluator_version(
        self, evaluator_id: str, version: str, limit: int = 50
    ) -> list[EvaluationRun]:
        return self._list_runs_by_asset(
            "evaluator", "", evaluator_id, version, limit=limit
        )

    def _run_asset_references(
        self,
        db: sqlite3.Connection,
        run: EvaluationRun,
    ) -> list[tuple[str, str, str, str, str, str]]:
        manifest = run.manifest
        dataset = manifest.dataset
        references = [
            (
                run.id,
                "dataset",
                "",
                dataset.dataset_id,
                str(dataset.version),
                dataset.content_sha256,
            )
        ]
        references.extend(
            (
                run.id,
                "case",
                dataset.dataset_id,
                case.id,
                str(dataset.version),
                content_sha256(case),
            )
            for case in manifest.execution_cases
        )

        target = manifest.target
        references.append(
            (
                run.id,
                target.ref.target_type.value,
                target.ref.source_id,
                target.ref.external_target_id,
                target.ref.external_version_id,
                target.descriptor_sha256,
            )
        )
        descriptor_row = db.execute(
            "SELECT payload FROM target_descriptors WHERE content_sha256=?",
            (target.descriptor_sha256,),
        ).fetchone()
        if descriptor_row is not None:
            descriptor = TargetDescriptor.model_validate_json(descriptor_row[0])
            if descriptor.ref != target.ref:
                raise ValueError(
                    "TargetDescriptor reference does not match TargetSnapshot"
                )
            references.extend(
                (
                    run.id,
                    "skill",
                    descriptor.ref.source_id,
                    skill.external_skill_id,
                    skill.external_version_id,
                    content_sha256(skill),
                )
                for skill in descriptor.skills
            )

        references.extend(
            (
                run.id,
                "evaluator",
                "",
                evaluator.id,
                evaluator.version,
                evaluator.content_sha256,
            )
            for evaluator in manifest.evaluator_specs
        )
        return references

    def _list_runs_by_asset(
        self,
        asset_kind: str,
        source_id: str,
        asset_id: str,
        version: str,
        *,
        content_sha256: str | None = None,
        limit: int,
    ) -> list[EvaluationRun]:
        if limit < 1:
            raise ValueError("Run list limit must be at least 1")
        query = """
            SELECT runs.payload
            FROM run_asset_refs
            JOIN runs ON runs.id=run_asset_refs.run_id
            WHERE asset_kind=? AND source_id=? AND asset_id=? AND version=?
        """
        parameters: tuple[object, ...] = (
            asset_kind,
            source_id,
            asset_id,
            version,
        )
        if content_sha256 is not None:
            query += " AND content_sha256=?"
            parameters += (content_sha256,)
        query += " ORDER BY runs.created_at DESC, runs.id LIMIT ?"
        parameters += (limit,)
        with self._connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [EvaluationRun.model_validate_json(row[0]) for row in rows]

    def claim_pending_run(
        self, run_id: str, started_at: datetime
    ) -> EvaluationRun | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                return None

            pending = EvaluationRun.model_validate_json(row[0])
            if pending.status is not RunStatus.PENDING:
                return None
            running = transition_run(
                pending, RunStatus.RUNNING, occurred_at=started_at
            )
            cursor = db.execute(
                """
                UPDATE runs SET status=?, payload=?
                WHERE id=? AND status='pending'
                """,
                (running.status, canonical_json(running), run_id),
            )
            return running if cursor.rowcount == 1 else None

    def cancel_run(
        self, run_id: str, cancelled_at: datetime
    ) -> EvaluationRun | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                return None

            current = EvaluationRun.model_validate_json(row[0])
            if current.status not in {RunStatus.PENDING, RunStatus.RUNNING}:
                return None
            cancelled = transition_run(
                current,
                RunStatus.CANCELLED,
                occurred_at=cancelled_at,
            )
            cursor = db.execute(
                """
                UPDATE runs SET status=?, payload=?
                WHERE id=? AND status=?
                """,
                (
                    cancelled.status,
                    canonical_json(cancelled),
                    run_id,
                    current.status,
                ),
            )
            return cancelled if cursor.rowcount == 1 else None

    def list_runs_by_status(
        self,
        status: RunStatus,
        limit: int | None = None,
        oldest_first: bool = False,
    ) -> list[EvaluationRun]:
        if limit is not None and limit < 1:
            raise ValueError("Run list limit must be at least 1")
        direction = "ASC" if oldest_first else "DESC"
        query = (
            "SELECT payload FROM runs WHERE status=? "
            f"ORDER BY created_at {direction}, id"
        )
        parameters: tuple[object, ...] = (status.value,)
        if limit is not None:
            query += " LIMIT ?"
            parameters += (limit,)
        with self._connect() as db:
            rows = db.execute(query, parameters).fetchall()
        return [EvaluationRun.model_validate_json(row[0]) for row in rows]

    def count_runs_by_status(self) -> dict[RunStatus, int]:
        counts = {status: 0 for status in RunStatus}
        with self._connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM runs GROUP BY status"
            ).fetchall()
        for row in rows:
            counts[RunStatus(row["status"])] = row["count"]
        return counts
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


def _require_user_evaluator(evaluator: Evaluator) -> None:
    if evaluator.source != EvaluatorSource.USER:
        raise ValueError("only user Evaluators can be persisted")


def _parse_evaluator_version(version: str) -> int:
    if (
        not isinstance(version, str)
        or not version.isascii()
        or not version.isdecimal()
    ):
        raise ValueError("Evaluator version must be a canonical positive integer")
    parsed = int(version)
    if parsed < 1 or str(parsed) != version:
        raise ValueError("Evaluator version must be a canonical positive integer")
    return parsed


def _load_evaluator_spec(row: sqlite3.Row) -> EvaluatorSpec:
    spec = EvaluatorSpec.model_validate_json(row["payload"])
    if spec.version != str(row["version"]):
        raise ValueError("stored Evaluator version does not match its payload")
    if spec.content_sha256 != row["content_sha256"]:
        raise ValueError("stored Evaluator content hash does not match its payload")
    return spec
