from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from openabm_api.ids import new_id
from openabm_api.time import utc_now

ROOT = Path(__file__).resolve().parents[4]
MIGRATION_DIR = ROOT / "infra" / "migrations"


def encode_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def decode_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            for migration in sorted(MIGRATION_DIR.glob("*.sql")):
                conn.executescript(migration.read_text())
            self.ensure_project("proj_demo", "Demo Project")

    def ensure_project(self, project_id: str, name: str | None = None) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO projects(project_id, name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id) DO NOTHING
                """,
                (project_id, name or project_id, now),
            )

    def upsert_trace(self, trace: dict[str, Any]) -> str:
        now = utc_now()
        self.ensure_project(trace["project_id"])
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_metadata(
                  trace_id, project_id, session_id, user_external_id, root_span_id,
                  environment, status, started_at, ended_at, tags_json, attributes_json,
                  summary, server_received_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                  session_id = excluded.session_id,
                  user_external_id = excluded.user_external_id,
                  root_span_id = excluded.root_span_id,
                  environment = excluded.environment,
                  status = excluded.status,
                  started_at = excluded.started_at,
                  ended_at = excluded.ended_at,
                  tags_json = excluded.tags_json,
                  attributes_json = excluded.attributes_json,
                  summary = excluded.summary,
                  updated_at = excluded.updated_at
                """,
                (
                    trace["trace_id"],
                    trace["project_id"],
                    trace.get("session_id"),
                    trace.get("user_external_id"),
                    trace.get("root_span_id"),
                    trace.get("environment") or "default",
                    trace.get("status") or "unknown",
                    trace["started_at"],
                    trace.get("ended_at"),
                    encode_json(trace.get("tags", [])),
                    encode_json(trace.get("attributes", {})),
                    trace.get("summary"),
                    now,
                    now,
                ),
            )
            self._index_trace(conn, trace["project_id"], trace["trace_id"])
        return trace["trace_id"]

    def upsert_span(self, span: dict[str, Any], idempotency_key: str | None = None) -> str:
        del idempotency_key
        now = utc_now()
        self.ensure_project(span["project_id"])
        existing = self.get_span(span["project_id"], span["span_id"])
        if existing is not None:
            self._record_diagnostic(
                span["project_id"],
                span["trace_id"],
                span["span_id"],
                "duplicate_span_update",
                "Span updated by duplicate span_id ingest.",
                existing,
            )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_spans(
                  span_id, trace_id, project_id, parent_span_id, name, span_type, status,
                  started_at, ended_at, input_json, output_json, attributes_json,
                  events_json, links_json, server_received_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(span_id) DO UPDATE SET
                  trace_id = excluded.trace_id,
                  project_id = excluded.project_id,
                  parent_span_id = excluded.parent_span_id,
                  name = excluded.name,
                  span_type = excluded.span_type,
                  status = excluded.status,
                  started_at = excluded.started_at,
                  ended_at = excluded.ended_at,
                  input_json = excluded.input_json,
                  output_json = excluded.output_json,
                  attributes_json = excluded.attributes_json,
                  events_json = excluded.events_json,
                  links_json = excluded.links_json,
                  server_received_at = excluded.server_received_at,
                  updated_at = excluded.updated_at
                """,
                (
                    span["span_id"],
                    span["trace_id"],
                    span["project_id"],
                    span.get("parent_span_id"),
                    span["name"],
                    span["span_type"],
                    span.get("status") or "unknown",
                    span["started_at"],
                    span.get("ended_at"),
                    encode_json(span.get("input")),
                    encode_json(span.get("output")),
                    encode_json(span.get("attributes", {})),
                    encode_json(span.get("events", [])),
                    encode_json(span.get("links", [])),
                    span.get("server_received_at") or now,
                    now,
                ),
            )
            self._index_trace(conn, span["project_id"], span["trace_id"])
        return span["span_id"]

    def append_event(
        self,
        project_id: str,
        trace_id: str,
        span_id: str,
        event: dict[str, Any],
    ) -> str:
        span = self.get_span(project_id, span_id)
        if span is None:
            raise KeyError(f"span not found: {span_id}")
        span["events"].append(event)
        self.upsert_span(span)
        return span_id

    def put_payload(self, payload: dict[str, Any]) -> str:
        self.ensure_project(payload["project_id"])
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO payload_objects(
                  payload_id, project_id, trace_id, span_id, content_type,
                  byte_size_nullable, sha256_nullable, redaction_state, storage_uri,
                  created_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(payload_id) DO UPDATE SET
                  redaction_state = excluded.redaction_state,
                  storage_uri = excluded.storage_uri
                """,
                (
                    payload["payload_id"],
                    payload["project_id"],
                    payload.get("trace_id"),
                    payload.get("span_id"),
                    payload["content_type"],
                    payload.get("byte_size_nullable"),
                    payload.get("sha256_nullable"),
                    payload["redaction_state"],
                    payload.get("storage_uri"),
                    payload["created_at"],
                ),
            )
        return payload["payload_id"]

    def list_projects(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT project_id, name, created_at FROM projects ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_trace(self, project_id: str, trace_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM trace_metadata
                WHERE project_id = ? AND trace_id = ?
                """,
                (project_id, trace_id),
            ).fetchone()
        return self._trace_from_row(row) if row else None

    def list_spans(self, project_id: str, trace_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trace_spans
                WHERE project_id = ? AND trace_id = ?
                ORDER BY started_at ASC, server_received_at ASC
                """,
                (project_id, trace_id),
            ).fetchall()
        return [self._span_from_row(row) for row in rows]

    def get_span(self, project_id: str, span_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM trace_spans
                WHERE project_id = ? AND span_id = ?
                """,
                (project_id, span_id),
            ).fetchone()
        return self._span_from_row(row) if row else None

    def search_traces(
        self,
        project_id: str,
        filters: dict[str, Any] | None = None,
        full_text_query: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        filters = filters or {}
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if filters.get("status"):
            clauses.append("status = ?")
            params.append(filters["status"])
        if filters.get("environment"):
            clauses.append("environment = ?")
            params.append(filters["environment"])
        if filters.get("trace_id"):
            clauses.append("trace_id = ?")
            params.append(filters["trace_id"])
        if filters.get("time_from"):
            clauses.append("started_at >= ?")
            params.append(filters["time_from"])
        if filters.get("time_to"):
            clauses.append("started_at <= ?")
            params.append(filters["time_to"])

        sql = "SELECT * FROM trace_metadata WHERE " + " AND ".join(clauses)
        if full_text_query:
            sql += (
                " AND trace_id IN (SELECT trace_id FROM trace_search_fts "
                "WHERE project_id = ? AND trace_search_fts MATCH ?)"
            )
            params.extend([project_id, full_text_query])
        sql += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._trace_from_row(row) for row in rows]

    def list_scores(self, project_id: str, trace_id: str | None = None) -> list[dict[str, Any]]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scores WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._score_from_row(row) for row in rows]

    def list_behaviors(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM behaviors WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._behavior_from_row(row) for row in rows]

    def create_dataset(
        self,
        project_id: str,
        name: str,
        description: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        dataset_id = new_id("dataset")
        dataset_version_id = new_id("dataset_version")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO datasets(dataset_id, project_id, name, description, status, created_at)
                VALUES (?, ?, ?, ?, 'draft', ?)
                """,
                (dataset_id, project_id, name, description, now),
            )
            conn.execute(
                """
                INSERT INTO dataset_versions(
                  dataset_version_id, dataset_id, version, immutable, created_at
                )
                VALUES (?, ?, 1, 1, ?)
                """,
                (dataset_version_id, dataset_id, now),
            )
        return {
            "dataset_id": dataset_id,
            "project_id": project_id,
            "name": name,
            "description": description,
            "status": "draft",
            "created_at": now,
            "latest_version_id": dataset_version_id,
        }

    def list_datasets(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*, dv.dataset_version_id AS latest_version_id
                FROM datasets d
                LEFT JOIN dataset_versions dv ON dv.dataset_id = d.dataset_id
                WHERE d.project_id = ?
                ORDER BY d.created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_trace_to_dataset(
        self,
        project_id: str,
        dataset_id: str,
        trace_id: str,
        labels: list[str] | None = None,
        created_from: str = "manual",
    ) -> dict[str, Any]:
        trace = self.get_trace(project_id, trace_id)
        if trace is None:
            raise KeyError(f"trace not found: {trace_id}")
        with self.connect() as conn:
            version = conn.execute(
                """
                SELECT dataset_version_id FROM dataset_versions
                WHERE dataset_id = ?
                ORDER BY version DESC
                LIMIT 1
                """,
                (dataset_id,),
            ).fetchone()
            if version is None:
                raise KeyError(f"dataset not found: {dataset_id}")
            dataset_version_id = version["dataset_version_id"]
            example_id = new_id("dataset_example")
            now = utc_now()
            example = {
                "dataset_example_id": example_id,
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "source_trace_id": trace_id,
                "source_span_id": trace.get("root_span_id"),
                "input": None,
                "expected_output": None,
                "expected_scores": [],
                "labels": labels or [],
                "metadata": {"trace_summary": trace.get("summary")},
                "split": "unspecified",
                "created_from": created_from,
                "created_at": now,
            }
            conn.execute(
                """
                INSERT INTO dataset_examples(
                  dataset_example_id, project_id, dataset_id, dataset_version_id,
                  source_trace_id, source_span_id, input_json, expected_output_json,
                  expected_scores_json, labels_json, metadata_json, split,
                  created_from, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    example_id,
                    project_id,
                    dataset_id,
                    dataset_version_id,
                    trace_id,
                    trace.get("root_span_id"),
                    encode_json(None),
                    encode_json(None),
                    encode_json([]),
                    encode_json(labels or []),
                    encode_json(example["metadata"]),
                    "unspecified",
                    created_from,
                    now,
                ),
            )
        return example

    def list_dataset_examples(self, project_id: str, dataset_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM dataset_examples
                WHERE project_id = ? AND dataset_id = ?
                ORDER BY created_at DESC
                """,
                (project_id, dataset_id),
            ).fetchall()
        return [self._dataset_example_from_row(row) for row in rows]

    def append_audit(
        self,
        action: str,
        target_type: str,
        project_id: str | None = None,
        target_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        actor_id: str | None = None,
    ) -> str:
        audit_id = new_id("audit")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_log(
                  audit_id, project_id, actor_id, action, target_type, target_id,
                  metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    project_id,
                    actor_id,
                    action,
                    target_type,
                    target_id,
                    encode_json(metadata or {}),
                    utc_now(),
                ),
            )
        return audit_id

    def _record_diagnostic(
        self,
        project_id: str,
        trace_id: str | None,
        span_id: str | None,
        diagnostic_type: str,
        message: str,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_diagnostics(
                  diagnostic_id, project_id, trace_id, span_id, diagnostic_type,
                  message, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("diag"),
                    project_id,
                    trace_id,
                    span_id,
                    diagnostic_type,
                    message,
                    encode_json(payload),
                    utc_now(),
                ),
            )

    def _index_trace(self, conn: sqlite3.Connection, project_id: str, trace_id: str) -> None:
        trace = conn.execute(
            "SELECT * FROM trace_metadata WHERE project_id = ? AND trace_id = ?",
            (project_id, trace_id),
        ).fetchone()
        spans = conn.execute(
            "SELECT * FROM trace_spans WHERE project_id = ? AND trace_id = ?",
            (project_id, trace_id),
        ).fetchall()
        parts: list[str] = []
        if trace:
            parts.extend(
                [
                    trace["summary"] or "",
                    trace["status"] or "",
                    trace["environment"] or "",
                    trace["tags_json"] or "",
                    trace["attributes_json"] or "",
                ]
            )
        for span in spans:
            parts.extend(
                [
                    span["name"],
                    span["span_type"],
                    span["status"],
                    span["attributes_json"],
                    span["events_json"],
                    span["input_json"] or "",
                    span["output_json"] or "",
                ]
            )
        body = "\n".join(parts)
        conn.execute(
            "DELETE FROM trace_search_fts WHERE project_id = ? AND trace_id = ?",
            (project_id, trace_id),
        )
        conn.execute(
            "INSERT INTO trace_search_fts(trace_id, project_id, body) VALUES (?, ?, ?)",
            (trace_id, project_id, body),
        )

    @staticmethod
    def _trace_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "trace_id": row["trace_id"],
            "project_id": row["project_id"],
            "session_id": row["session_id"],
            "user_external_id": row["user_external_id"],
            "root_span_id": row["root_span_id"],
            "environment": row["environment"],
            "status": row["status"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "tags": decode_json(row["tags_json"], []),
            "attributes": decode_json(row["attributes_json"], {}),
            "summary": row["summary"],
            "server_received_at": row["server_received_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _span_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "trace_id": row["trace_id"],
            "span_id": row["span_id"],
            "parent_span_id": row["parent_span_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "span_type": row["span_type"],
            "status": row["status"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "input": decode_json(row["input_json"], None),
            "output": decode_json(row["output_json"], None),
            "attributes": decode_json(row["attributes_json"], {}),
            "events": decode_json(row["events_json"], []),
            "links": decode_json(row["links_json"], []),
            "server_received_at": row["server_received_at"],
        }

    @staticmethod
    def _score_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "score_id": row["score_id"],
            "trace_id": row["trace_id"],
            "span_id": row["span_id"],
            "judge_id": row["judge_id"],
            "judge_version_id": row["judge_version_id"],
            "status": row["status"],
            "value": decode_json(row["value_json"], None),
            "confidence": row["confidence"],
            "reasoning": row["reasoning"],
            "evidence_span_ids": decode_json(row["evidence_span_ids_json"], []),
            "failure_mode": row["failure_mode"],
            "cost": decode_json(row["cost_json"], None),
            "latency_ms": row["latency_ms"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _behavior_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "behavior_id": row["behavior_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "description": row["description"],
            "severity": row["severity"],
            "detector": decode_json(row["detector_json"], {}),
            "status": row["status"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _dataset_example_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "dataset_example_id": row["dataset_example_id"],
            "dataset_id": row["dataset_id"],
            "dataset_version_id": row["dataset_version_id"],
            "source_trace_id": row["source_trace_id"],
            "source_span_id": row["source_span_id"],
            "input": decode_json(row["input_json"], None),
            "expected_output": decode_json(row["expected_output_json"], None),
            "expected_scores": decode_json(row["expected_scores_json"], []),
            "labels": decode_json(row["labels_json"], []),
            "metadata": decode_json(row["metadata_json"], {}),
            "split": row["split"],
            "created_from": row["created_from"],
            "created_at": row["created_at"],
        }


def ingest_fixture(store: SQLiteStore, fixtures: Iterable[dict[str, Any]]) -> None:
    for fixture in fixtures:
        store.upsert_trace(fixture["trace"])
        for span in fixture["spans"]:
            store.upsert_span(span)
