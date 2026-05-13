from __future__ import annotations

import difflib
import hashlib
import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from openabm_api.ids import new_id
from openabm_api.prompts import SECRET_REF_PATTERN, prompt_commit_id
from openabm_api.time import utc_now

ROOT = Path(__file__).resolve().parents[4]
MIGRATION_DIR = ROOT / "infra" / "migrations"


def encode_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def decode_json(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value)


def _payload_metadata_only(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in payload.items()
            if key not in {"storage_uri"}
        }
        for payload in payloads
    ]


def _included_classifications(sections: dict[str, Any]) -> list[str]:
    classifications = set()
    for item in sections.get("context_packs", []):
        if item.get("classification"):
            classifications.add(item["classification"])
    for item in sections.get("payloads", []):
        if item.get("redaction_state"):
            classifications.add(str(item["redaction_state"]))
    return sorted(classifications or {"unspecified"})


def _agent_config_commit_id(
    *,
    content: dict[str, Any],
    metadata: dict[str, Any],
    version: int,
) -> str:
    payload = {"content": content, "metadata": metadata, "version": version}
    digest = hashlib.sha256(encode_json(payload).encode()).hexdigest()
    return f"agent_config_{digest[:32]}"


def _first_eval_verdict(result: dict[str, Any] | None) -> str | None:
    if not result or not result.get("scores"):
        return None
    return (result["scores"][0].get("value") or {}).get("verdict")


def _pass_rate(summary: dict[str, Any]) -> float:
    verdicts = summary.get("score_verdict_counts", {})
    total = sum(int(count) for count in verdicts.values())
    if total == 0:
        return 0.0
    return int(verdicts.get("pass", 0)) / total


def _invalid_delta(baseline: dict[str, Any], candidate: dict[str, Any]) -> int:
    baseline_invalid = int(baseline.get("result_status_counts", {}).get("invalid_output", 0))
    candidate_invalid = int(candidate.get("result_status_counts", {}).get("invalid_output", 0))
    return candidate_invalid - baseline_invalid


def _average_score(results: Iterable[dict[str, Any]]) -> float | None:
    scores = []
    for result in results:
        for score in result.get("scores", []):
            value = score.get("value") or {}
            if isinstance(value.get("score"), int | float):
                scores.append(float(value["score"]))
    if not scores:
        return None
    return sum(scores) / len(scores)


def _average_numbers(values: Iterable[int | float | None]) -> float | None:
    numbers = [float(value) for value in values if isinstance(value, int | float)]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _sum_latency(results: Iterable[dict[str, Any]]) -> int:
    return sum(int(result.get("latency_ms") or 0) for result in results)


def _sum_token_usage(results: Iterable[dict[str, Any]]) -> int | None:
    total = 0
    saw_usage = False
    for result in results:
        for score in result.get("scores", []):
            usage = ((score.get("cost") or {}).get("usage") or {}) if score.get("cost") else {}
            tokens = usage.get("total_tokens")
            if isinstance(tokens, int | float):
                saw_usage = True
                total += int(tokens)
    return total if saw_usage else None


def _score_verdict_counts(scores: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for score in scores:
        verdict = str((score.get("value") or {}).get("verdict") or "unknown")
        counts[verdict] = counts.get(verdict, 0) + 1
    return counts


def _score_status_counts(scores: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for score in scores:
        status = str(score.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _score_status_rate(scores: list[dict[str, Any]], status: str) -> float | None:
    if not scores:
        return None
    return _score_status_counts(scores).get(status, 0) / len(scores)


def _review_label_counts(tasks: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        decision = str(task.get("decision_nullable") or task.get("status") or "unknown")
        counts[decision] = counts.get(decision, 0) + 1
    return counts


def _review_decision_count(tasks: Iterable[dict[str, Any]], decision: str) -> int:
    return sum(1 for task in tasks if task.get("decision_nullable") == decision)


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
            self._ensure_automation_run_cooldown_columns(conn)
            self.ensure_project("proj_demo", "Demo Project")

    @staticmethod
    def _ensure_automation_run_cooldown_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(automation_runs)").fetchall()
        }
        if "cooldown_key" not in columns:
            conn.execute("ALTER TABLE automation_runs ADD COLUMN cooldown_key TEXT")
        if "cooldown_result_json" not in columns:
            conn.execute("ALTER TABLE automation_runs ADD COLUMN cooldown_result_json TEXT")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_automation_runs_cooldown
              ON automation_runs(project_id, automation_id, cooldown_key, completed_at)
              WHERE cooldown_key IS NOT NULL
            """
        )

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
        if filters.get("session_id"):
            clauses.append("session_id = ?")
            params.append(filters["session_id"])
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

    def record_score(self, project_id: str, score: dict[str, Any]) -> dict[str, Any]:
        self.ensure_project(project_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO scores(
                  score_id, project_id, trace_id, span_id, judge_id,
                  judge_version_id, status, value_json, confidence, reasoning,
                  evidence_span_ids_json, failure_mode, cost_json, latency_ms,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score["score_id"],
                    project_id,
                    score["trace_id"],
                    score.get("span_id"),
                    score["judge_id"],
                    score.get("judge_version_id"),
                    score["status"],
                    encode_json(score.get("value")),
                    score.get("confidence"),
                    score.get("reasoning"),
                    encode_json(score.get("evidence_span_ids") or []),
                    score.get("failure_mode"),
                    encode_json(score.get("cost")),
                    score.get("latency_ms"),
                    score["created_at"],
                ),
            )
        return score

    def create_judge(
        self,
        request: dict[str, Any],
        *,
        definition: dict[str, Any] | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(request["project_id"])
        now = utc_now()
        judge = {
            "judge_id": request.get("judge_id") or new_id("judge"),
            "project_id": request["project_id"],
            "name": request["name"],
            "description": request.get("description"),
            "judge_type": request["judge_type"],
            "status": request.get("status") or "draft",
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO judges(
                  judge_id, project_id, name, description, judge_type, status,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    judge["judge_id"],
                    judge["project_id"],
                    judge["name"],
                    judge["description"],
                    judge["judge_type"],
                    judge["status"],
                    judge["created_at"],
                    judge["updated_at"],
                ),
            )
        if definition is not None:
            version = self.commit_judge_version(
                judge["project_id"],
                judge["judge_id"],
                definition=definition,
                created_by=created_by,
            )
            judge["versions"] = [version]
        return judge

    def commit_judge_version(
        self,
        project_id: str,
        judge_id: str,
        *,
        definition: dict[str, Any],
        created_by: str | None = None,
    ) -> dict[str, Any]:
        if self.get_judge(project_id, judge_id) is None:
            raise KeyError(f"judge not found: {judge_id}")
        with self.connect() as conn:
            latest = conn.execute(
                """
                SELECT COALESCE(MAX(version), 0) AS latest
                FROM judge_versions
                WHERE project_id = ? AND judge_id = ?
                """,
                (project_id, judge_id),
            ).fetchone()
            version_number = int(latest["latest"]) + 1
            now = utc_now()
            version = {
                "judge_version_id": new_id("judge_version"),
                "judge_id": judge_id,
                "project_id": project_id,
                "version": version_number,
                "definition": definition,
                "created_by": created_by,
                "created_at": now,
            }
            conn.execute(
                """
                INSERT INTO judge_versions(
                  judge_version_id, judge_id, project_id, version,
                  definition_json, created_by, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version["judge_version_id"],
                    judge_id,
                    project_id,
                    version_number,
                    encode_json(definition),
                    created_by,
                    now,
                ),
            )
        return version

    def list_judges(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM judges
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._judge_from_row(row) for row in rows]

    def get_judge(self, project_id: str, judge_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM judges
                WHERE project_id = ? AND judge_id = ?
                """,
                (project_id, judge_id),
            ).fetchone()
            versions = conn.execute(
                """
                SELECT * FROM judge_versions
                WHERE project_id = ? AND judge_id = ?
                ORDER BY version DESC
                """,
                (project_id, judge_id),
            ).fetchall()
        if row is None:
            return None
        judge = self._judge_from_row(row)
        judge["versions"] = [self._judge_version_from_row(version) for version in versions]
        return judge

    def list_behaviors(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM behaviors WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._behavior_from_row(row) for row in rows]

    def get_behavior(self, project_id: str, behavior_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM behaviors
                WHERE project_id = ? AND behavior_id = ?
                """,
                (project_id, behavior_id),
            ).fetchone()
        return self._behavior_from_row(row) if row else None

    def create_behavior(self, request: dict[str, Any]) -> dict[str, Any]:
        self.ensure_project(request["project_id"])
        now = utc_now()
        behavior = {
            "behavior_id": request.get("behavior_id") or new_id("behavior"),
            "project_id": request["project_id"],
            "name": request["name"],
            "description": request.get("description"),
            "severity": request.get("severity") or "medium",
            "detector": request.get("detector") or {"type": "manual_label"},
            "status": request.get("status") or "draft",
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO behaviors(
                  behavior_id, project_id, name, description, severity,
                  detector_json, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    behavior["behavior_id"],
                    behavior["project_id"],
                    behavior["name"],
                    behavior["description"],
                    behavior["severity"],
                    encode_json(behavior["detector"]),
                    behavior["status"],
                    behavior["created_at"],
                ),
            )
        return behavior

    def replace_behavior_backtest_matches(
        self,
        project_id: str,
        behavior_id: str,
        positive_examples: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        now = utc_now()
        matches = []
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM behavior_matches
                WHERE project_id = ? AND behavior_id = ? AND status = 'backtest_positive'
                """,
                (project_id, behavior_id),
            )
            for example in positive_examples:
                match = {
                    "behavior_match_id": new_id("behavior_match"),
                    "project_id": project_id,
                    "behavior_id": behavior_id,
                    "trace_id": example["trace_id"],
                    "span_id": (example.get("evidence_span_ids") or [None])[0],
                    "score_id": None,
                    "status": "backtest_positive",
                    "evidence_span_ids": example.get("evidence_span_ids", []),
                    "created_at": now,
                }
                conn.execute(
                    """
                    INSERT INTO behavior_matches(
                      behavior_match_id, project_id, behavior_id, trace_id, span_id,
                      score_id, status, evidence_span_ids_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match["behavior_match_id"],
                        match["project_id"],
                        match["behavior_id"],
                        match["trace_id"],
                        match["span_id"],
                        match["score_id"],
                        match["status"],
                        encode_json(match["evidence_span_ids"]),
                        match["created_at"],
                    ),
                )
                matches.append(match)
        return matches

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

    def get_dataset(self, project_id: str, dataset_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT d.*, dv.dataset_version_id AS latest_version_id
                FROM datasets d
                LEFT JOIN dataset_versions dv ON dv.dataset_id = d.dataset_id
                WHERE d.project_id = ? AND d.dataset_id = ?
                ORDER BY dv.version DESC
                LIMIT 1
                """,
                (project_id, dataset_id),
            ).fetchone()
        return dict(row) if row else None

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

    def list_dataset_examples_by_version(
        self,
        project_id: str,
        dataset_version_id: str,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM dataset_examples
                WHERE project_id = ? AND dataset_version_id = ?
                ORDER BY created_at DESC
                """,
                (project_id, dataset_version_id),
            ).fetchall()
        return [self._dataset_example_from_row(row) for row in rows]

    def create_eval_run(
        self,
        project_id: str,
        dataset_version_id: str,
        runner: dict[str, Any],
        judges: list[dict[str, Any]],
        baseline_eval_run_id: str | None = None,
        prompt_version_id: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        now = utc_now()
        item = {
            "eval_run_id": new_id("eval_run"),
            "project_id": project_id,
            "dataset_version_id": dataset_version_id,
            "baseline_eval_run_id": baseline_eval_run_id,
            "runner": runner,
            "judges": judges,
            "prompt_version_id": prompt_version_id,
            "status": "running",
            "summary": {},
            "created_at": now,
            "completed_at": None,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO eval_runs(
                  eval_run_id, project_id, dataset_version_id, baseline_eval_run_id,
                  runner_json, judges_json, prompt_version_id, status, summary_json,
                  created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["eval_run_id"],
                    project_id,
                    dataset_version_id,
                    baseline_eval_run_id,
                    encode_json(runner),
                    encode_json(judges),
                    prompt_version_id,
                    "running",
                    encode_json({}),
                    now,
                    None,
                ),
            )
        return item

    def complete_eval_run(
        self,
        project_id: str,
        eval_run_id: str,
        summary: dict[str, Any],
        status: str = "completed",
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE eval_runs
                SET status = ?, summary_json = ?, completed_at = ?
                WHERE project_id = ? AND eval_run_id = ?
                """,
                (status, encode_json(summary), now, project_id, eval_run_id),
            )
            row = conn.execute(
                """
                SELECT * FROM eval_runs
                WHERE project_id = ? AND eval_run_id = ?
                """,
                (project_id, eval_run_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"eval run not found: {eval_run_id}")
        return self._eval_run_from_row(row)

    def record_eval_result(
        self,
        project_id: str,
        eval_run_id: str,
        dataset_example_id: str,
        status: str,
        scores: list[dict[str, Any]],
        offline_trace_id: str | None = None,
        cost: dict[str, Any] | None = None,
        latency_ms: int | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        item = {
            "eval_result_id": new_id("eval_result"),
            "project_id": project_id,
            "eval_run_id": eval_run_id,
            "dataset_example_id": dataset_example_id,
            "offline_trace_id": offline_trace_id,
            "status": status,
            "scores": scores,
            "cost": cost,
            "latency_ms": latency_ms,
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO eval_results(
                  eval_result_id, project_id, eval_run_id, dataset_example_id,
                  offline_trace_id, status, scores_json, cost_json, latency_ms,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["eval_result_id"],
                    project_id,
                    eval_run_id,
                    dataset_example_id,
                    offline_trace_id,
                    status,
                    encode_json(scores),
                    encode_json(cost),
                    latency_ms,
                    now,
                ),
            )
        return item

    def list_eval_runs(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM eval_runs
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._eval_run_from_row(row) for row in rows]

    def list_eval_results(self, project_id: str, eval_run_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM eval_results
                WHERE project_id = ? AND eval_run_id = ?
                ORDER BY created_at ASC
                """,
                (project_id, eval_run_id),
            ).fetchall()
        return [self._eval_result_from_row(row) for row in rows]

    def get_eval_run(self, project_id: str, eval_run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM eval_runs
                WHERE project_id = ? AND eval_run_id = ?
                """,
                (project_id, eval_run_id),
            ).fetchone()
        return self._eval_run_from_row(row) if row else None

    def compare_eval_runs(
        self,
        project_id: str,
        baseline_eval_run_id: str,
        candidate_eval_run_id: str,
    ) -> dict[str, Any]:
        baseline = self.get_eval_run(project_id, baseline_eval_run_id)
        candidate = self.get_eval_run(project_id, candidate_eval_run_id)
        if baseline is None or candidate is None:
            raise KeyError("eval run not found")
        baseline_results = {
            result["dataset_example_id"]: result
            for result in self.list_eval_results(project_id, baseline_eval_run_id)
        }
        candidate_results = {
            result["dataset_example_id"]: result
            for result in self.list_eval_results(project_id, candidate_eval_run_id)
        }
        example_ids = sorted(set(baseline_results) | set(candidate_results))
        new_failures = []
        fixed_failures = []
        unchanged_failures = []
        for example_id in example_ids:
            old_verdict = _first_eval_verdict(baseline_results.get(example_id))
            new_verdict = _first_eval_verdict(candidate_results.get(example_id))
            if old_verdict != "fail" and new_verdict == "fail":
                new_failures.append(example_id)
            elif old_verdict == "fail" and new_verdict != "fail":
                fixed_failures.append(example_id)
            elif old_verdict == "fail" and new_verdict == "fail":
                unchanged_failures.append(example_id)
        baseline_score = _average_score(baseline_results.values())
        candidate_score = _average_score(candidate_results.values())
        baseline_tokens = _sum_token_usage(baseline_results.values())
        candidate_tokens = _sum_token_usage(candidate_results.values())
        return {
            "baseline_eval_run_id": baseline_eval_run_id,
            "candidate_eval_run_id": candidate_eval_run_id,
            "baseline_summary": baseline["summary"],
            "candidate_summary": candidate["summary"],
            "pass_rate_delta": _pass_rate(candidate["summary"]) - _pass_rate(baseline["summary"]),
            "avg_score_delta": None
            if baseline_score is None or candidate_score is None
            else candidate_score - baseline_score,
            "new_failures": new_failures,
            "fixed_failures": fixed_failures,
            "unchanged_failures": unchanged_failures,
            "invalid_judge_output_delta": _invalid_delta(baseline["summary"], candidate["summary"]),
            "cost_delta": None,
            "latency_delta": _sum_latency(candidate_results.values())
            - _sum_latency(baseline_results.values()),
            "token_delta": None
            if baseline_tokens is None or candidate_tokens is None
            else candidate_tokens - baseline_tokens,
            "behavior_distribution_shift": {},
        }

    def build_judge_calibration_report(
        self,
        project_id: str,
        judge_id: str,
    ) -> dict[str, Any]:
        judge = self.get_judge(project_id, judge_id)
        if judge is None:
            raise KeyError(f"judge not found: {judge_id}")
        judge_aliases = {
            judge_id,
            *[
                version.get("definition", {}).get("judge_id")
                for version in judge.get("versions", [])
                if version.get("definition", {}).get("judge_id")
            ],
        }

        matching_scores = []
        eval_run_ids = set()
        per_run: dict[str, list[dict[str, Any]]] = {}
        for run in self.list_eval_runs(project_id):
            run_scores = []
            for result in self.list_eval_results(project_id, run["eval_run_id"]):
                for score in result.get("scores", []):
                    if score.get("judge_id") not in judge_aliases:
                        continue
                    scored = {
                        **score,
                        "registry_judge_id": judge_id,
                        "eval_run_id": run["eval_run_id"],
                        "dataset_example_id": result["dataset_example_id"],
                    }
                    matching_scores.append(scored)
                    run_scores.append(scored)
                    eval_run_ids.add(run["eval_run_id"])
            if run_scores:
                per_run[run["eval_run_id"]] = run_scores

        review_labels = [
            task
            for task in self.list_review_tasks(project_id, task_type="judge_output")
            if task["source_entity_id"] == judge_id
            or (
                task["source_entity_type"] == "judge"
                and task["source_entity_id"] == judge_id
            )
        ]
        return {
            "judge_id": judge_id,
            "project_id": project_id,
            "score_count": len(matching_scores),
            "eval_run_ids": sorted(eval_run_ids),
            "verdict_counts": _score_verdict_counts(matching_scores),
            "status_counts": _score_status_counts(matching_scores),
            "invalid_output_rate": _score_status_rate(matching_scores, "invalid_output"),
            "avg_score": _average_score([{"scores": matching_scores}]),
            "latency_ms": {
                "avg": _average_numbers(score.get("latency_ms") for score in matching_scores),
                "total": sum(int(score.get("latency_ms") or 0) for score in matching_scores),
            },
            "token_usage": _sum_token_usage([{"scores": matching_scores}]),
            "human_review_labels": _review_label_counts(review_labels),
            "false_positive_reports": _review_decision_count(review_labels, "false_positive"),
            "false_negative_reports": _review_decision_count(review_labels, "false_negative"),
            "drift_report": [
                {
                    "eval_run_id": eval_run_id,
                    "score_count": len(scores),
                    "verdict_counts": _score_verdict_counts(scores),
                    "invalid_output_rate": _score_status_rate(scores, "invalid_output"),
                }
                for eval_run_id, scores in sorted(per_run.items())
            ],
        }

    def add_trace_dimension(
        self,
        project_id: str,
        trace_id: str,
        key: str,
        value: str,
        value_type: str = "string",
        source: str = "manual",
    ) -> dict[str, Any]:
        if self.get_trace(project_id, trace_id) is None:
            raise KeyError(f"trace not found: {trace_id}")
        item = {
            "trace_dimension_id": new_id("trace_dimension"),
            "trace_id": trace_id,
            "project_id": project_id,
            "key": key,
            "value": value,
            "value_type": value_type,
            "source": source,
            "created_at": utc_now(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_dimensions(
                  trace_dimension_id, trace_id, project_id, key, value, value_type,
                  source, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["trace_dimension_id"],
                    trace_id,
                    project_id,
                    key,
                    value,
                    value_type,
                    source,
                    item["created_at"],
                ),
            )
        return item

    def list_trace_dimensions(
        self,
        project_id: str,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trace_dimensions WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def create_saved_search(
        self,
        project_id: str,
        name: str,
        query: dict[str, Any],
        owner_user_id: str | None = None,
        visibility: str = "project",
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        now = utc_now()
        item = {
            "saved_search_id": new_id("saved_search"),
            "project_id": project_id,
            "name": name,
            "query": query,
            "owner_user_id": owner_user_id,
            "visibility": visibility,
            "query_contract_version": "v1",
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO saved_searches(
                  saved_search_id, project_id, name, query_json, owner_user_id,
                  visibility, query_contract_version, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["saved_search_id"],
                    project_id,
                    name,
                    encode_json(query),
                    owner_user_id,
                    visibility,
                    "v1",
                    now,
                    now,
                ),
            )
        return item

    def list_saved_searches(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM saved_searches WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        return [self._saved_search_from_row(row) for row in rows]

    def get_saved_search(self, project_id: str, saved_search_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM saved_searches
                WHERE project_id = ? AND saved_search_id = ?
                """,
                (project_id, saved_search_id),
            ).fetchone()
        return self._saved_search_from_row(row) if row else None

    def create_prompt(self, request: dict[str, Any]) -> dict[str, Any]:
        self.ensure_project(request["project_id"])
        now = utc_now()
        prompt = {
            "prompt_id": request.get("prompt_id") or new_id("prompt"),
            "project_id": request["project_id"],
            "name": request["name"],
            "description": request.get("description"),
            "tags": request.get("tags") or {},
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO prompts(
                  prompt_id, project_id, name, description, tags_json,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prompt["prompt_id"],
                    prompt["project_id"],
                    prompt["name"],
                    prompt["description"],
                    encode_json(prompt["tags"]),
                    prompt["created_at"],
                    prompt["updated_at"],
                ),
            )
        return prompt

    def list_prompts(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM prompts
                WHERE project_id = ?
                ORDER BY updated_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._prompt_from_row(row) for row in rows]

    def get_prompt(self, project_id: str, prompt_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM prompts
                WHERE project_id = ? AND prompt_id = ?
                """,
                (project_id, prompt_id),
            ).fetchone()
            versions = conn.execute(
                """
                SELECT * FROM prompt_versions
                WHERE project_id = ? AND prompt_id = ?
                ORDER BY created_at DESC
                """,
                (project_id, prompt_id),
            ).fetchall()
        if row is None:
            return None
        prompt = self._prompt_from_row(row)
        prompt["versions"] = [self._prompt_version_from_row(version) for version in versions]
        return prompt

    def commit_prompt_version(
        self,
        project_id: str,
        prompt_id: str,
        *,
        template_text: str,
        variables_schema: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        parent_commit_id: str | None = None,
        tag: str | None = None,
    ) -> dict[str, Any]:
        if SECRET_REF_PATTERN.search(template_text):
            raise ValueError("Secret interpolation is disallowed in prompt templates.")
        if self.get_prompt(project_id, prompt_id) is None:
            raise KeyError(f"prompt not found: {prompt_id}")
        commit_id = prompt_commit_id(
            template_text=template_text,
            variables_schema=variables_schema,
            parent_commit_id=parent_commit_id,
            metadata=metadata,
        )
        now = utc_now()
        version = {
            "prompt_version_id": new_id("prompt_version"),
            "prompt_id": prompt_id,
            "project_id": project_id,
            "commit_id": commit_id,
            "parent_commit_id": parent_commit_id,
            "template_text": template_text,
            "variables_schema": variables_schema,
            "metadata": metadata or {},
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO prompt_versions(
                  prompt_version_id, prompt_id, project_id, commit_id,
                  parent_commit_id, template_text, variables_schema_json,
                  metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version["prompt_version_id"],
                    prompt_id,
                    project_id,
                    commit_id,
                    parent_commit_id,
                    template_text,
                    encode_json(variables_schema),
                    encode_json(metadata or {}),
                    now,
                ),
            )
            if tag:
                self._move_prompt_tag(conn, project_id, prompt_id, tag, commit_id, now)
        return version

    def get_prompt_version_by_commit(
        self,
        project_id: str,
        prompt_id: str,
        commit_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM prompt_versions
                WHERE project_id = ? AND prompt_id = ? AND commit_id = ?
                """,
                (project_id, prompt_id, commit_id),
            ).fetchone()
        return self._prompt_version_from_row(row) if row else None

    def diff_prompt_versions(
        self,
        project_id: str,
        prompt_id: str,
        old_commit_id: str,
        new_commit_id: str,
    ) -> dict[str, Any]:
        old = self.get_prompt_version_by_commit(project_id, prompt_id, old_commit_id)
        new = self.get_prompt_version_by_commit(project_id, prompt_id, new_commit_id)
        if old is None or new is None:
            raise KeyError("prompt version not found")
        text_diff = "\n".join(
            difflib.unified_diff(
                old["template_text"].splitlines(),
                new["template_text"].splitlines(),
                fromfile=old_commit_id,
                tofile=new_commit_id,
                lineterm="",
            )
        )
        return {
            "prompt_id": prompt_id,
            "old_commit_id": old_commit_id,
            "new_commit_id": new_commit_id,
            "text_diff": text_diff,
            "variables_schema_changed": old["variables_schema"] != new["variables_schema"],
        }

    def _move_prompt_tag(
        self,
        conn: sqlite3.Connection,
        project_id: str,
        prompt_id: str,
        tag: str,
        commit_id: str,
        now: str,
    ) -> None:
        row = conn.execute(
            """
            SELECT tags_json FROM prompts
            WHERE project_id = ? AND prompt_id = ?
            """,
            (project_id, prompt_id),
        ).fetchone()
        tags = decode_json(row["tags_json"], {}) if row else {}
        previous = tags.get(tag)
        tags[tag] = commit_id
        conn.execute(
            """
            UPDATE prompts
            SET tags_json = ?, updated_at = ?
            WHERE project_id = ? AND prompt_id = ?
            """,
            (encode_json(tags), now, project_id, prompt_id),
        )
        conn.execute(
            """
            INSERT INTO prompt_tag_events(
              prompt_tag_event_id, prompt_id, project_id, tag,
              previous_commit_id, new_commit_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id("prompt_tag_event"),
                prompt_id,
                project_id,
                tag,
                previous,
                commit_id,
                now,
            ),
        )

    def create_agent_config(self, request: dict[str, Any]) -> dict[str, Any]:
        self.ensure_project(request["project_id"])
        now = utc_now()
        config = {
            "agent_config_id": request.get("agent_config_id") or new_id("agent_config"),
            "project_id": request["project_id"],
            "name": request["name"],
            "config_type": request["config_type"],
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_configs(
                  agent_config_id, project_id, name, config_type, created_at
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    config["agent_config_id"],
                    config["project_id"],
                    config["name"],
                    config["config_type"],
                    config["created_at"],
                ),
            )
        return config

    def list_agent_configs(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM agent_configs
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._agent_config_from_row(row) for row in rows]

    def get_agent_config(
        self,
        project_id: str,
        agent_config_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_configs
                WHERE project_id = ? AND agent_config_id = ?
                """,
                (project_id, agent_config_id),
            ).fetchone()
            versions = conn.execute(
                """
                SELECT * FROM agent_config_versions
                WHERE agent_config_id = ?
                ORDER BY version DESC
                """,
                (agent_config_id,),
            ).fetchall()
        if row is None:
            return None
        config = self._agent_config_from_row(row)
        config["versions"] = [
            self._agent_config_version_from_row(version) for version in versions
        ]
        return config

    def commit_agent_config_version(
        self,
        project_id: str,
        agent_config_id: str,
        *,
        content: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.get_agent_config(project_id, agent_config_id) is None:
            raise KeyError(f"agent config not found: {agent_config_id}")
        with self.connect() as conn:
            latest = conn.execute(
                """
                SELECT COALESCE(MAX(version), 0) AS latest
                FROM agent_config_versions
                WHERE agent_config_id = ?
                """,
                (agent_config_id,),
            ).fetchone()
            version_number = int(latest["latest"]) + 1
            commit_id = _agent_config_commit_id(
                content=content,
                metadata=metadata or {},
                version=version_number,
            )
            now = utc_now()
            version = {
                "agent_config_version_id": new_id("agent_config_version"),
                "agent_config_id": agent_config_id,
                "version": version_number,
                "commit_id": commit_id,
                "content": content,
                "metadata": metadata or {},
                "created_at": now,
            }
            conn.execute(
                """
                INSERT INTO agent_config_versions(
                  agent_config_version_id, agent_config_id, version, commit_id,
                  content_json, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version["agent_config_version_id"],
                    agent_config_id,
                    version_number,
                    commit_id,
                    encode_json(content),
                    encode_json(metadata or {}),
                    now,
                ),
            )
        return version

    def compare_agent_config_versions(
        self,
        project_id: str,
        agent_config_id: str,
        old_commit_id: str,
        new_commit_id: str,
    ) -> dict[str, Any]:
        config = self.get_agent_config(project_id, agent_config_id)
        if config is None:
            raise KeyError(f"agent config not found: {agent_config_id}")
        versions = {version["commit_id"]: version for version in config["versions"]}
        old = versions.get(old_commit_id)
        new = versions.get(new_commit_id)
        if old is None or new is None:
            raise KeyError("agent config version not found")
        diff = "\n".join(
            difflib.unified_diff(
                encode_json(old["content"]).splitlines(),
                encode_json(new["content"]).splitlines(),
                fromfile=old_commit_id,
                tofile=new_commit_id,
                lineterm="",
            )
        )
        return {
            "agent_config_id": agent_config_id,
            "old_commit_id": old_commit_id,
            "new_commit_id": new_commit_id,
            "content_diff": diff,
            "metadata_changed": old["metadata"] != new["metadata"],
        }

    def create_issue(self, request: dict[str, Any]) -> dict[str, Any]:
        project_id = request["project_id"]
        self.ensure_project(project_id)
        now = utc_now()
        item = {
            "issue_id": new_id("issue"),
            "project_id": project_id,
            "source_type": request.get("source_type", "manual"),
            "source_ref_nullable": request.get("source_ref_nullable"),
            "reporter_nullable": request.get("reporter_nullable"),
            "title": request["title"],
            "description": request.get("description", ""),
            "screenshot_payload_id_nullable": request.get("screenshot_payload_id_nullable"),
            "seed_trace_id_nullable": request.get("seed_trace_id_nullable"),
            "seed_session_id_nullable": request.get("seed_session_id_nullable"),
            "status": "open",
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO issues(
                  issue_id, project_id, source_type, source_ref_nullable,
                  reporter_nullable, title, description,
                  screenshot_payload_id_nullable, seed_trace_id_nullable,
                  seed_session_id_nullable, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["issue_id"],
                    project_id,
                    item["source_type"],
                    item["source_ref_nullable"],
                    item["reporter_nullable"],
                    item["title"],
                    item["description"],
                    item["screenshot_payload_id_nullable"],
                    item["seed_trace_id_nullable"],
                    item["seed_session_id_nullable"],
                    item["status"],
                    now,
                    now,
                ),
            )
        return item

    def list_issues(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM issues WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_data_classification_policy(self, request: dict[str, Any]) -> dict[str, Any]:
        project_id = request["project_id"]
        self.ensure_project(project_id)
        now = utc_now()
        item = {
            "policy_id": new_id("classification_policy"),
            "project_id": project_id,
            "default_classification": request.get("default_classification", "internal"),
            "rules": request.get("rules") or [],
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO data_classification_policies(
                  policy_id, project_id, default_classification, rules_json,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["policy_id"],
                    project_id,
                    item["default_classification"],
                    encode_json(item["rules"]),
                    now,
                    now,
                ),
            )
        return item

    def list_data_classification_policies(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM data_classification_policies
                WHERE project_id = ?
                ORDER BY updated_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._data_classification_policy_from_row(row) for row in rows]

    def create_retention_policy(self, request: dict[str, Any]) -> dict[str, Any]:
        self.ensure_project(request["project_id"])
        now = utc_now()
        policy = {
            "retention_policy_id": request.get("retention_policy_id")
            or new_id("retention_policy"),
            "project_id": request["project_id"],
            "name": request["name"],
            "rules": request.get("rules") or [],
            "status": request.get("status") or "draft",
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO retention_policies(
                  retention_policy_id, project_id, name, rules_json, status,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy["retention_policy_id"],
                    policy["project_id"],
                    policy["name"],
                    encode_json(policy["rules"]),
                    policy["status"],
                    policy["created_at"],
                    policy["updated_at"],
                ),
            )
        return policy

    def list_retention_policies(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM retention_policies
                WHERE project_id = ?
                ORDER BY updated_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._retention_policy_from_row(row) for row in rows]

    def create_review_task(self, request: dict[str, Any]) -> dict[str, Any]:
        self.ensure_project(request["project_id"])
        now = utc_now()
        task = {
            "review_task_id": request.get("review_task_id") or new_id("review_task"),
            "project_id": request["project_id"],
            "task_type": request["task_type"],
            "source_entity_type": request["source_entity_type"],
            "source_entity_id": request["source_entity_id"],
            "assigned_to_nullable": request.get("assigned_to_nullable"),
            "status": request.get("status") or "open",
            "decision_nullable": request.get("decision_nullable"),
            "notes_nullable": request.get("notes_nullable"),
            "evidence_ids": request.get("evidence_ids") or [],
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO review_tasks(
                  review_task_id, project_id, task_type, source_entity_type,
                  source_entity_id, assigned_to_nullable, status, decision_nullable,
                  notes_nullable, evidence_ids_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task["review_task_id"],
                    task["project_id"],
                    task["task_type"],
                    task["source_entity_type"],
                    task["source_entity_id"],
                    task["assigned_to_nullable"],
                    task["status"],
                    task["decision_nullable"],
                    task["notes_nullable"],
                    encode_json(task["evidence_ids"]),
                    task["created_at"],
                    task["updated_at"],
                ),
            )
        return task

    def list_review_tasks(
        self,
        project_id: str,
        status: str | None = None,
        task_type: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM review_tasks WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._review_task_from_row(row) for row in rows]

    def update_review_task(
        self,
        project_id: str,
        review_task_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.get_review_task(project_id, review_task_id)
        if current is None:
            raise KeyError(f"review task not found: {review_task_id}")
        updated = {
            **current,
            "status": patch.get("status", current["status"]),
            "decision_nullable": patch.get(
                "decision_nullable",
                patch.get("decision", current["decision_nullable"]),
            ),
            "notes_nullable": patch.get(
                "notes_nullable",
                patch.get("notes", current["notes_nullable"]),
            ),
            "updated_at": utc_now(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE review_tasks
                SET status = ?, decision_nullable = ?, notes_nullable = ?, updated_at = ?
                WHERE project_id = ? AND review_task_id = ?
                """,
                (
                    updated["status"],
                    updated["decision_nullable"],
                    updated["notes_nullable"],
                    updated["updated_at"],
                    project_id,
                    review_task_id,
                ),
            )
        return updated

    def get_review_task(
        self,
        project_id: str,
        review_task_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM review_tasks
                WHERE project_id = ? AND review_task_id = ?
                """,
                (project_id, review_task_id),
            ).fetchone()
        return self._review_task_from_row(row) if row else None

    def create_notification_target(self, request: dict[str, Any]) -> dict[str, Any]:
        self.ensure_project(request["project_id"])
        now = utc_now()
        target = {
            "target_id": request.get("target_id") or new_id("notification_target"),
            "project_id": request["project_id"],
            "type": request["type"],
            "display_name": request["display_name"],
            "config_secret_refs": request.get("config_secret_refs") or [],
            "created_by": request.get("created_by"),
            "status": request.get("status") or "active",
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_targets(
                  target_id, project_id, type, display_name, config_secret_refs_json,
                  created_by, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target["target_id"],
                    target["project_id"],
                    target["type"],
                    target["display_name"],
                    encode_json(target["config_secret_refs"]),
                    target["created_by"],
                    target["status"],
                    target["created_at"],
                    target["updated_at"],
                ),
            )
        return target

    def list_notification_targets(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM notification_targets
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._notification_target_from_row(row) for row in rows]

    def get_notification_target(
        self,
        project_id: str,
        target_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM notification_targets
                WHERE project_id = ? AND target_id = ?
                """,
                (project_id, target_id),
            ).fetchone()
        return self._notification_target_from_row(row) if row else None

    def create_automation(self, request: dict[str, Any]) -> dict[str, Any]:
        self.ensure_project(request["project_id"])
        now = utc_now()
        automation = {
            "automation_id": request.get("automation_id") or new_id("automation"),
            "project_id": request["project_id"],
            "name": request["name"],
            "trigger": request["trigger"],
            "conditions": request.get("conditions") or {"combine": "all", "items": []},
            "actions": request.get("actions") or [],
            "cooldown": request.get("cooldown"),
            "status": request.get("status") or "draft",
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO automations(
                  automation_id, project_id, name, trigger_json, conditions_json,
                  actions_json, cooldown_json, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    automation["automation_id"],
                    automation["project_id"],
                    automation["name"],
                    encode_json(automation["trigger"]),
                    encode_json(automation["conditions"]),
                    encode_json(automation["actions"]),
                    encode_json(automation["cooldown"]),
                    automation["status"],
                    automation["created_at"],
                    automation["updated_at"],
                ),
            )
        return automation

    def list_automations(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM automations
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._automation_from_row(row) for row in rows]

    def get_automation(self, project_id: str, automation_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM automations
                WHERE project_id = ? AND automation_id = ?
                """,
                (project_id, automation_id),
            ).fetchone()
        return self._automation_from_row(row) if row else None

    def get_automation_run_by_idempotency(
        self,
        project_id: str,
        automation_id: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM automation_runs
                WHERE project_id = ? AND automation_id = ? AND idempotency_key = ?
                """,
                (project_id, automation_id, idempotency_key),
            ).fetchone()
        return self._automation_run_from_row(row) if row else None

    def get_latest_automation_run_for_cooldown(
        self,
        project_id: str,
        automation_id: str,
        cooldown_key: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM automation_runs
                WHERE project_id = ?
                  AND automation_id = ?
                  AND cooldown_key = ?
                  AND status IN ('succeeded', 'partial_failure')
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                (project_id, automation_id, cooldown_key),
            ).fetchone()
        return self._automation_run_from_row(row) if row else None

    def record_automation_run(self, run: dict[str, Any]) -> dict[str, Any]:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO automation_runs(
                  automation_run_id, automation_id, project_id, trigger_entity_type,
                  trigger_entity_id, idempotency_key, cooldown_key, status,
                  condition_result_json, cooldown_result_json, action_results_json,
                  started_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["automation_run_id"],
                    run["automation_id"],
                    run["project_id"],
                    run.get("trigger_entity_type"),
                    run.get("trigger_entity_id"),
                    run.get("idempotency_key"),
                    run.get("cooldown_key"),
                    run["status"],
                    encode_json(run["condition_result"]),
                    encode_json(run.get("cooldown_result") or {"configured": False}),
                    encode_json(run["action_results"]),
                    run["started_at"],
                    run.get("completed_at"),
                ),
            )
        return run

    def get_issue(self, project_id: str, issue_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM issues
                WHERE project_id = ? AND issue_id = ?
                """,
                (project_id, issue_id),
            ).fetchone()
        return dict(row) if row else None

    def create_agent_context_pack(
        self,
        *,
        project_id: str,
        source_trace_ids: list[str],
        content: dict[str, Any],
        classification: str,
        issue_id: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        now = utc_now()
        item = {
            "context_pack_id": new_id("context_pack"),
            "project_id": project_id,
            "issue_id_nullable": issue_id,
            "source_trace_ids": source_trace_ids,
            "content": content,
            "classification": classification,
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_context_packs(
                  context_pack_id, project_id, issue_id_nullable,
                  source_trace_ids_json, content_json, classification, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["context_pack_id"],
                    project_id,
                    issue_id,
                    encode_json(source_trace_ids),
                    encode_json(content),
                    classification,
                    now,
                ),
            )
        return item

    def list_agent_context_packs(
        self,
        project_id: str,
        issue_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if issue_id:
            clauses.append("issue_id_nullable = ?")
            params.append(issue_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_context_packs WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._agent_context_pack_from_row(row) for row in rows]

    def get_agent_context_pack(
        self,
        project_id: str,
        context_pack_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM agent_context_packs
                WHERE project_id = ? AND context_pack_id = ?
                """,
                (project_id, context_pack_id),
            ).fetchone()
        return self._agent_context_pack_from_row(row) if row else None

    def list_investigation_runs(
        self,
        project_id: str,
        issue_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if issue_id:
            clauses.append("issue_id_nullable = ?")
            params.append(issue_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigation_runs WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._investigation_run_from_row(row) for row in rows]

    def get_investigation_run(
        self,
        project_id: str,
        investigation_run_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM investigation_runs
                WHERE project_id = ? AND investigation_run_id = ?
                """,
                (project_id, investigation_run_id),
            ).fetchone()
        return self._investigation_run_from_row(row) if row else None

    def start_investigation(self, request: dict[str, Any]) -> dict[str, Any]:
        project_id = request["project_id"]
        query = request.get("natural_language_problem_nullable") or request.get("query") or ""
        filters = request.get("filters") or {}
        seed_trace_id = request.get("seed_trace_id_nullable")
        traces = self.search_traces(
            project_id,
            filters=filters,
            full_text_query=query or None,
            limit=int(request.get("limit", 50)),
        )
        if seed_trace_id and all(trace["trace_id"] != seed_trace_id for trace in traces):
            seed = self.get_trace(project_id, seed_trace_id)
            if seed is not None:
                traces.insert(0, seed)
        report = self._build_impact_report(
            project_id=project_id,
            issue_id=request.get("issue_id_nullable"),
            investigation_run_id=None,
            traces=traces,
            time_window=request.get("time_window") or {},
        )
        now = utc_now()
        run = {
            "investigation_run_id": new_id("investigation_run"),
            "project_id": project_id,
            "issue_id_nullable": request.get("issue_id_nullable"),
            "seed_trace_id_nullable": seed_trace_id,
            "seed_session_id_nullable": request.get("seed_session_id_nullable"),
            "natural_language_problem_nullable": query or None,
            "time_window": request.get("time_window") or {},
            "filters": filters,
            "allowed_tools": request.get("allowed_tools")
            or ["structured_search", "full_text_search"],
            "status": "completed",
            "result": {
                "impact_report": report,
                "evidence_trace_ids": [trace["trace_id"] for trace in traces],
                "suspected_root_causes": report["suspected_root_causes"],
                "recommended_next_actions": [
                    "review representative traces",
                    "create or backtest a behavior detector",
                    "add confirmed examples to a dataset",
                ],
                "llm_deferred": [
                    "semantic similarity",
                    "natural-language root-cause narrative",
                    "model-drafted judge or behavior",
                ],
            },
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO investigation_runs(
                  investigation_run_id, project_id, issue_id_nullable,
                  seed_trace_id_nullable, seed_session_id_nullable,
                  natural_language_problem_nullable, time_window_json, filters_json,
                  allowed_tools_json, status, result_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run["investigation_run_id"],
                    project_id,
                    run["issue_id_nullable"],
                    seed_trace_id,
                    run["seed_session_id_nullable"],
                    run["natural_language_problem_nullable"],
                    encode_json(run["time_window"]),
                    encode_json(filters),
                    encode_json(run["allowed_tools"]),
                    "completed",
                    encode_json(run["result"]),
                    now,
                    now,
                ),
            )
        report = self.persist_impact_report(report, run["investigation_run_id"])
        run["result"]["impact_report"] = report
        return run

    def update_investigation_result(
        self,
        project_id: str,
        investigation_run_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE investigation_runs
                SET result_json = ?, updated_at = ?
                WHERE project_id = ? AND investigation_run_id = ?
                """,
                (encode_json(result), now, project_id, investigation_run_id),
            )
            row = conn.execute(
                """
                SELECT * FROM investigation_runs
                WHERE project_id = ? AND investigation_run_id = ?
                """,
                (project_id, investigation_run_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"investigation run not found: {investigation_run_id}")
        return self._investigation_run_from_row(row)

    def persist_impact_report(
        self,
        report: dict[str, Any],
        investigation_run_id: str | None,
    ) -> dict[str, Any]:
        report = {**report, "investigation_run_id": investigation_run_id}
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO impact_reports(
                  report_id, project_id, issue_id, investigation_run_id,
                  time_window_json, matching_trace_count, affected_session_count,
                  affected_entity_count, affected_entities_json,
                  task_type_distribution_json, dimension_distribution_json,
                  behavior_distribution_json, deployment_distribution_json,
                  suspected_root_causes_json, representative_trace_ids_json,
                  generated_summary, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report["report_id"],
                    report["project_id"],
                    report.get("issue_id"),
                    investigation_run_id,
                    encode_json(report["time_window"]),
                    report["matching_trace_count"],
                    report["affected_session_count"],
                    report["affected_entity_count"],
                    encode_json(report["affected_entities"]),
                    encode_json(report["task_type_distribution"]),
                    encode_json(report["dimension_distribution"]),
                    encode_json(report["behavior_distribution"]),
                    encode_json(report["deployment_distribution"]),
                    encode_json(report["suspected_root_causes"]),
                    encode_json(report["representative_trace_ids"]),
                    report["generated_summary"],
                    report["created_at"],
                ),
            )
        return report

    def list_impact_reports(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM impact_reports WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [self._impact_report_from_row(row) for row in rows]

    def get_impact_report(self, project_id: str, report_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM impact_reports
                WHERE project_id = ? AND report_id = ?
                """,
                (project_id, report_id),
            ).fetchone()
        return self._impact_report_from_row(row) if row else None

    def create_grounding_check(
        self,
        project_id: str,
        trace_id: str,
        result: dict[str, Any],
        span_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        check = {
            "grounding_check_id": new_id("grounding_check"),
            "project_id": project_id,
            "trace_id": trace_id,
            "span_id_nullable": span_id,
            "status": result["status"],
            "claims": result["claims"],
            "evidence_span_ids": result["evidence_span_ids"],
            "created_at": now,
        }
        if result.get("model_extraction"):
            check["model_extraction"] = result["model_extraction"]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO grounding_checks(
                  grounding_check_id, project_id, trace_id, span_id_nullable,
                  status, claims_json, evidence_span_ids_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    check["grounding_check_id"],
                    project_id,
                    trace_id,
                    span_id,
                    check["status"],
                    encode_json(check["claims"]),
                    encode_json(check["evidence_span_ids"]),
                    now,
                ),
            )
            if result.get("model_extraction"):
                conn.execute(
                    """
                    INSERT INTO grounding_check_model_extractions(
                      grounding_check_id, project_id, model_extraction_json, created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        check["grounding_check_id"],
                        project_id,
                        encode_json(result["model_extraction"]),
                        now,
                    ),
                )
        return check

    def list_grounding_checks(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM grounding_checks
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
            extraction_rows = conn.execute(
                """
                SELECT grounding_check_id, model_extraction_json
                FROM grounding_check_model_extractions
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchall()
        extractions = {
            row["grounding_check_id"]: decode_json(row["model_extraction_json"], {})
            for row in extraction_rows
        }
        checks = [self._grounding_check_from_row(row) for row in rows]
        for check in checks:
            if check["grounding_check_id"] in extractions:
                check["model_extraction"] = extractions[check["grounding_check_id"]]
        return checks

    def create_novelty_run(
        self,
        project_id: str,
        input_payload: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        run = {
            "novelty_run_id": new_id("novelty_run"),
            "project_id": project_id,
            "input": input_payload,
            "result": result,
            "status": "succeeded",
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO novel_behavior_detection_runs(
                  novelty_run_id, project_id, input_json, result_json, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run["novelty_run_id"],
                    project_id,
                    encode_json(input_payload),
                    encode_json(result),
                    run["status"],
                    now,
                ),
            )
        return run

    def list_novelty_runs(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM novel_behavior_detection_runs
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._novelty_run_from_row(row) for row in rows]

    def export_project_bundle(
        self,
        project_id: str,
        *,
        include_payloads: bool = False,
    ) -> dict[str, Any]:
        traces = self.search_traces(project_id, limit=10000)
        trace_ids = [trace["trace_id"] for trace in traces]
        spans = [span for trace_id in trace_ids for span in self.list_spans(project_id, trace_id)]
        payloads = self._list_payload_objects(project_id)
        sections: dict[str, Any] = {
            "traces": traces,
            "spans": spans,
            "payloads": payloads if include_payloads else _payload_metadata_only(payloads),
            "scores": self.list_scores(project_id),
            "judges": self.list_judges(project_id),
            "eval_runs": self.list_eval_runs(project_id),
            "behaviors": self.list_behaviors(project_id),
            "datasets": self.list_datasets(project_id),
            "issues": self.list_issues(project_id),
            "investigations": self.list_investigation_runs(project_id),
            "impact_reports": self.list_impact_reports(project_id),
            "context_packs": self.list_agent_context_packs(project_id),
            "review_tasks": self.list_review_tasks(project_id),
            "grounding_checks": self.list_grounding_checks(project_id),
            "novelty_runs": self.list_novelty_runs(project_id),
        }
        manifest = {
            "export_id": new_id("export"),
            "project_id": project_id,
            "created_at": utc_now(),
            "include_payloads": include_payloads,
            "included_classifications": _included_classifications(sections),
            "sections": {
                name: {
                    "count": len(value) if isinstance(value, list) else 1,
                    "sha256": hashlib.sha256(encode_json(value).encode()).hexdigest(),
                }
                for name, value in sections.items()
            },
        }
        return {"metadata": {"project_id": project_id}, "manifest": manifest, **sections}

    def tombstone_trace(self, project_id: str, trace_id: str) -> dict[str, Any]:
        trace = self.get_trace(project_id, trace_id)
        if trace is None:
            raise KeyError(f"trace not found: {trace_id}")
        now = utc_now()
        effects: dict[str, int] = {}
        with self.connect() as conn:
            for table, column in [
                ("trace_spans", "trace_id"),
                ("scores", "trace_id"),
                ("behavior_matches", "trace_id"),
            ]:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE project_id = ? AND {column} = ?",
                    (project_id, trace_id),
                )
                effects[table] = cursor.rowcount
            cursor = conn.execute(
                """
                UPDATE payload_objects
                SET storage_uri = NULL, redaction_state = 'deleted', deleted_at = ?
                WHERE project_id = ? AND trace_id = ?
                """,
                (now, project_id, trace_id),
            )
            effects["payload_objects"] = cursor.rowcount
            cursor = conn.execute(
                """
                UPDATE trace_metadata
                SET status = 'deleted',
                    tags_json = ?,
                    attributes_json = ?,
                    summary = ?,
                    updated_at = ?
                WHERE project_id = ? AND trace_id = ?
                """,
                (
                    encode_json([]),
                    encode_json({"deleted_at": now}),
                    "Trace tombstoned by delete flow.",
                    now,
                    project_id,
                    trace_id,
                ),
            )
            effects["trace_metadata_tombstones"] = cursor.rowcount
            cursor = conn.execute(
                "DELETE FROM trace_search_fts WHERE project_id = ? AND trace_id = ?",
                (project_id, trace_id),
            )
            effects["trace_search_fts"] = cursor.rowcount
        return {
            "status": "tombstoned",
            "project_id": project_id,
            "trace_id": trace_id,
            "deleted_at": now,
            "effects": effects,
        }

    def _list_payload_objects(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM payload_objects
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _build_impact_report(
        self,
        project_id: str,
        issue_id: str | None,
        investigation_run_id: str | None,
        traces: list[dict[str, Any]],
        time_window: dict[str, Any],
    ) -> dict[str, Any]:
        dimensions = self.list_trace_dimensions(project_id)
        dimensions_by_trace: dict[str, list[dict[str, Any]]] = {}
        for dimension in dimensions:
            dimensions_by_trace.setdefault(dimension["trace_id"], []).append(dimension)
        trace_ids = [trace["trace_id"] for trace in traces]
        sessions = {trace.get("session_id") for trace in traces if trace.get("session_id")}
        dimension_distribution: dict[str, dict[str, int]] = {}
        affected_entities: dict[str, dict[str, Any]] = {}
        for trace_id in trace_ids:
            for dimension in dimensions_by_trace.get(trace_id, []):
                key = dimension["key"]
                value = dimension["value"]
                dimension_distribution.setdefault(key, {})
                dimension_distribution[key][value] = dimension_distribution[key].get(value, 0) + 1
                if key in {"account_id", "user_id", "external_ticket_id", "external_case_id"}:
                    entity_key = f"{key}:{value}"
                    affected_entities.setdefault(
                        entity_key,
                        {
                            "entity_type": key,
                            "entity_id": value,
                            "trace_ids": [],
                            "status": "needs_review",
                        },
                    )
                    affected_entities[entity_key]["trace_ids"].append(trace_id)
        suspected = []
        status_counts: dict[str, int] = {}
        for trace in traces:
            status = str(trace.get("status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1
        if status_counts:
            suspected.append(
                {
                    "candidate_id": new_id("root_cause_candidate"),
                    "hypothesis": "Trace cohort status distribution is overrepresented.",
                    "evidence_summary": status_counts,
                    "representative_trace_ids": trace_ids[:5],
                    "confidence_or_uncertainty": "deterministic_cohort_signal_only",
                }
            )
        now = utc_now()
        return {
            "report_id": new_id("impact_report"),
            "project_id": project_id,
            "issue_id": issue_id,
            "investigation_run_id": investigation_run_id,
            "time_window": time_window,
            "matching_trace_count": len(traces),
            "affected_session_count": len(sessions),
            "affected_entity_count": len(affected_entities),
            "affected_entities": list(affected_entities.values()),
            "task_type_distribution": dimension_distribution.get("task_type", {}),
            "dimension_distribution": dimension_distribution,
            "behavior_distribution": {},
            "deployment_distribution": {},
            "suspected_root_causes": suspected,
            "representative_trace_ids": trace_ids[:10],
            "generated_summary": (
                f"Deterministic investigation found {len(traces)} matching traces "
                f"across {len(sessions)} sessions."
            ),
            "created_at": now,
        }

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
    def _judge_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "judge_id": row["judge_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "description": row["description"],
            "judge_type": row["judge_type"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _judge_version_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "judge_version_id": row["judge_version_id"],
            "judge_id": row["judge_id"],
            "version": row["version"],
            "definition": decode_json(row["definition_json"], {}),
            "created_by": row["created_by"],
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
    def _review_task_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "review_task_id": row["review_task_id"],
            "project_id": row["project_id"],
            "task_type": row["task_type"],
            "source_entity_type": row["source_entity_type"],
            "source_entity_id": row["source_entity_id"],
            "assigned_to_nullable": row["assigned_to_nullable"],
            "status": row["status"],
            "decision_nullable": row["decision_nullable"],
            "notes_nullable": row["notes_nullable"],
            "evidence_ids": decode_json(row["evidence_ids_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _notification_target_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "target_id": row["target_id"],
            "project_id": row["project_id"],
            "type": row["type"],
            "display_name": row["display_name"],
            "config_secret_refs": decode_json(row["config_secret_refs_json"], []),
            "created_by": row["created_by"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _automation_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "automation_id": row["automation_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "trigger": decode_json(row["trigger_json"], {}),
            "conditions": decode_json(row["conditions_json"], {}),
            "actions": decode_json(row["actions_json"], []),
            "cooldown": decode_json(row["cooldown_json"], None),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _automation_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
        keys = set(row.keys())
        run = {
            "automation_run_id": row["automation_run_id"],
            "automation_id": row["automation_id"],
            "project_id": row["project_id"],
            "trigger_entity_type": row["trigger_entity_type"],
            "trigger_entity_id": row["trigger_entity_id"],
            "idempotency_key": row["idempotency_key"],
            "status": row["status"],
            "condition_result": decode_json(row["condition_result_json"], {}),
            "action_results": decode_json(row["action_results_json"], []),
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        }
        if "cooldown_key" in keys:
            run["cooldown_key"] = row["cooldown_key"]
        if "cooldown_result_json" in keys:
            run["cooldown_result"] = decode_json(row["cooldown_result_json"], {})
        return run

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

    @staticmethod
    def _eval_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "eval_run_id": row["eval_run_id"],
            "project_id": row["project_id"],
            "dataset_version_id": row["dataset_version_id"],
            "baseline_eval_run_id": row["baseline_eval_run_id"],
            "runner": decode_json(row["runner_json"], {}),
            "judges": decode_json(row["judges_json"], []),
            "prompt_version_id": row["prompt_version_id"],
            "status": row["status"],
            "summary": decode_json(row["summary_json"], {}),
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
        }

    @staticmethod
    def _eval_result_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "eval_result_id": row["eval_result_id"],
            "project_id": row["project_id"],
            "eval_run_id": row["eval_run_id"],
            "dataset_example_id": row["dataset_example_id"],
            "offline_trace_id": row["offline_trace_id"],
            "status": row["status"],
            "scores": decode_json(row["scores_json"], []),
            "cost": decode_json(row["cost_json"], None),
            "latency_ms": row["latency_ms"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _saved_search_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "saved_search_id": row["saved_search_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "query": decode_json(row["query_json"], {}),
            "owner_user_id": row["owner_user_id"],
            "visibility": row["visibility"],
            "query_contract_version": row["query_contract_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _prompt_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "prompt_id": row["prompt_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "description": row["description"],
            "tags": decode_json(row["tags_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _prompt_version_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "prompt_version_id": row["prompt_version_id"],
            "prompt_id": row["prompt_id"],
            "commit_id": row["commit_id"],
            "parent_commit_id": row["parent_commit_id"],
            "template_text": row["template_text"],
            "variables_schema": decode_json(row["variables_schema_json"], {}),
            "metadata": decode_json(row["metadata_json"], {}),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _agent_config_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "agent_config_id": row["agent_config_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "config_type": row["config_type"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _agent_config_version_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "agent_config_version_id": row["agent_config_version_id"],
            "agent_config_id": row["agent_config_id"],
            "version": row["version"],
            "commit_id": row["commit_id"],
            "content": decode_json(row["content_json"], {}),
            "metadata": decode_json(row["metadata_json"], {}),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _data_classification_policy_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "policy_id": row["policy_id"],
            "project_id": row["project_id"],
            "default_classification": row["default_classification"],
            "rules": decode_json(row["rules_json"], []),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _retention_policy_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "retention_policy_id": row["retention_policy_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "rules": decode_json(row["rules_json"], []),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _agent_context_pack_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "context_pack_id": row["context_pack_id"],
            "project_id": row["project_id"],
            "issue_id_nullable": row["issue_id_nullable"],
            "source_trace_ids": decode_json(row["source_trace_ids_json"], []),
            "content": decode_json(row["content_json"], {}),
            "classification": row["classification"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _investigation_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "investigation_run_id": row["investigation_run_id"],
            "project_id": row["project_id"],
            "issue_id_nullable": row["issue_id_nullable"],
            "seed_trace_id_nullable": row["seed_trace_id_nullable"],
            "seed_session_id_nullable": row["seed_session_id_nullable"],
            "natural_language_problem_nullable": row["natural_language_problem_nullable"],
            "time_window": decode_json(row["time_window_json"], {}),
            "filters": decode_json(row["filters_json"], {}),
            "allowed_tools": decode_json(row["allowed_tools_json"], []),
            "status": row["status"],
            "result": decode_json(row["result_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _impact_report_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "report_id": row["report_id"],
            "project_id": row["project_id"],
            "issue_id": row["issue_id"],
            "investigation_run_id": row["investigation_run_id"],
            "time_window": decode_json(row["time_window_json"], {}),
            "matching_trace_count": row["matching_trace_count"],
            "affected_session_count": row["affected_session_count"],
            "affected_entity_count": row["affected_entity_count"],
            "affected_entities": decode_json(row["affected_entities_json"], []),
            "task_type_distribution": decode_json(row["task_type_distribution_json"], {}),
            "dimension_distribution": decode_json(row["dimension_distribution_json"], {}),
            "behavior_distribution": decode_json(row["behavior_distribution_json"], {}),
            "deployment_distribution": decode_json(row["deployment_distribution_json"], {}),
            "suspected_root_causes": decode_json(row["suspected_root_causes_json"], []),
            "representative_trace_ids": decode_json(row["representative_trace_ids_json"], []),
            "generated_summary": row["generated_summary"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _grounding_check_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "grounding_check_id": row["grounding_check_id"],
            "project_id": row["project_id"],
            "trace_id": row["trace_id"],
            "span_id_nullable": row["span_id_nullable"],
            "status": row["status"],
            "claims": decode_json(row["claims_json"], []),
            "evidence_span_ids": decode_json(row["evidence_span_ids_json"], []),
            "created_at": row["created_at"],
        }

    @staticmethod
    def _novelty_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "novelty_run_id": row["novelty_run_id"],
            "project_id": row["project_id"],
            "input": decode_json(row["input_json"], {}),
            "result": decode_json(row["result_json"], {}),
            "status": row["status"],
            "created_at": row["created_at"],
        }


def ingest_fixture(store: SQLiteStore, fixtures: Iterable[dict[str, Any]]) -> None:
    for fixture in fixtures:
        store.upsert_trace(fixture["trace"])
        for span in fixture["spans"]:
            store.upsert_span(span)
