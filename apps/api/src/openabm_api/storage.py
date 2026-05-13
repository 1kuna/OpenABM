from __future__ import annotations

import difflib
import hashlib
import json
import secrets
import sqlite3
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from openabm_api.ids import new_id
from openabm_api.prompts import prompt_commit_id
from openabm_api.time import utc_now

ROOT = Path(__file__).resolve().parents[4]
MIGRATION_DIR = ROOT / "infra" / "migrations"
DEFAULT_ORG_ID = "org_local"
DEFAULT_OWNER_USER_ID = "user_local_owner"
DEFAULT_SERVICE_ACCOUNT_ID = "service_account_local_dev"
DEFAULT_DEV_API_KEY_ID = "api_key_local_dev"


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _auth_role(value: Any, default: str = "viewer") -> str:
    role = str(value or default)
    if role not in {"viewer", "developer", "admin", "owner"}:
        raise ValueError(f"Unsupported role: {role}")
    return role


def _future_timestamp(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=max(1, seconds))).isoformat()


def _auth_decision_records(now: str) -> list[dict[str, str]]:
    del now
    return [
        {
            "record_id": "auth_decision_local_passwordless",
            "topic": "password_or_passwordless",
            "decision": "passwordless_first",
            "rationale": (
                "The local reference implementation stores users, invites, sessions, "
                "and API keys, but defers password verification to a future identity "
                "provider integration point."
            ),
            "status": "accepted",
        },
        {
            "record_id": "auth_decision_session_cookie_policy",
            "topic": "session_cookie_policy",
            "decision": "http_only_same_site_lax_secure_in_production",
            "rationale": (
                "Browser sessions should use HTTP-only cookies, SameSite=Lax, CSRF "
                "tokens for mutating requests, and Secure cookies outside local dev."
            ),
            "status": "accepted",
        },
        {
            "record_id": "auth_decision_external_idp",
            "topic": "external_identity_provider_integration",
            "decision": "adapter_boundary_not_vendor_locked",
            "rationale": (
                "The API records external provider subject ids and auth providers so "
                "OAuth/OIDC can be integrated without rewriting project role checks."
            ),
            "status": "accepted",
        },
    ]


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


def _jsonl(items: Iterable[dict[str, Any]]) -> str:
    return "\n".join(encode_json(item) for item in items)


def _section_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        return len([line for line in value.splitlines() if line.strip()])
    return 1


def _remove_values(values: list[Any], removals: set[str]) -> tuple[list[Any], bool]:
    next_values = [value for value in values if str(value) not in removals]
    return next_values, len(next_values) != len(values)


def _scrub_json_references(value: Any, removals: set[str]) -> tuple[Any, bool]:
    if isinstance(value, list):
        changed = False
        next_values = []
        for item in value:
            if isinstance(item, str) and item in removals:
                changed = True
                continue
            scrubbed, item_changed = _scrub_json_references(item, removals)
            changed = changed or item_changed
            next_values.append(scrubbed)
        return next_values, changed
    if isinstance(value, dict):
        changed = False
        next_dict = {}
        for key, item in value.items():
            if isinstance(item, str) and item in removals:
                next_dict[key] = None
                changed = True
                continue
            scrubbed, item_changed = _scrub_json_references(item, removals)
            next_dict[key] = scrubbed
            changed = changed or item_changed
        return next_dict, changed
    return value, False


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


def _invalid_output_count(summary: dict[str, Any]) -> int:
    return int(summary.get("result_status_counts", {}).get("invalid_output", 0))


def _total_eval_examples(summary: dict[str, Any]) -> int:
    return int(summary.get("total_examples") or 0)


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


def _eval_group_summary(group_key: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    sorted_runs = sorted(runs, key=lambda run: run.get("created_at") or "", reverse=True)
    total_examples = sum(_total_eval_examples(run.get("summary", {})) for run in runs)
    invalid_outputs = sum(_invalid_output_count(run.get("summary", {})) for run in runs)
    return {
        "key": group_key,
        "run_count": len(runs),
        "completed_count": sum(1 for run in runs if run.get("status") == "completed"),
        "latest_eval_run_id": sorted_runs[0]["eval_run_id"] if sorted_runs else None,
        "latest_created_at": sorted_runs[0].get("created_at") if sorted_runs else None,
        "avg_pass_rate": _average_numbers([_pass_rate(run.get("summary", {})) for run in runs]),
        "total_examples": total_examples,
        "invalid_output_count": invalid_outputs,
        "invalid_output_rate": None
        if total_examples == 0
        else invalid_outputs / total_examples,
    }


def _group_eval_runs(
    runs: list[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        groups.setdefault(key_fn(run), []).append(run)
    return sorted(
        (_eval_group_summary(key, grouped_runs) for key, grouped_runs in groups.items()),
        key=lambda item: (item["run_count"], item["latest_created_at"] or ""),
        reverse=True,
    )


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


def _retention_trace_candidates(
    traces: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    *,
    now: str,
) -> list[str]:
    now_dt = _parse_utc_datetime(now)
    if now_dt is None:
        return []
    candidate_ids = set()
    for rule in rules:
        if rule.get("entity") != "traces":
            continue
        ttl_days = _non_negative_int(rule.get("ttl_days"))
        cutoff = now_dt - timedelta(days=ttl_days)
        for trace in traces:
            if trace.get("status") == "deleted":
                continue
            trace_dt = _parse_utc_datetime(trace.get("ended_at") or trace.get("started_at"))
            if trace_dt is not None and trace_dt <= cutoff:
                candidate_ids.add(trace["trace_id"])
    return sorted(candidate_ids)


def _worker_heartbeat_health(
    heartbeats: list[dict[str, Any]],
    *,
    now: str,
    stale_after_seconds: int = 900,
) -> list[dict[str, Any]]:
    now_dt = _parse_utc_datetime(now)
    health = []
    for heartbeat in heartbeats:
        last_seen = _parse_utc_datetime(heartbeat.get("last_seen_at"))
        age_seconds = (
            int((now_dt - last_seen).total_seconds())
            if now_dt is not None and last_seen is not None
            else None
        )
        if heartbeat.get("status") in {"error", "failed"}:
            status = "unhealthy"
        elif age_seconds is not None and age_seconds > stale_after_seconds:
            status = "stale"
        else:
            status = "healthy"
        health.append(
            {
                "worker_id": heartbeat["worker_id"],
                "worker_type": heartbeat["worker_type"],
                "status": status,
                "reported_status": heartbeat["status"],
                "queue_depth": heartbeat["queue_depth"],
                "last_seen_at": heartbeat["last_seen_at"],
                "last_seen_age_seconds": age_seconds,
                "stale_after_seconds": stale_after_seconds,
            }
        )
    return health


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _parse_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _runtime_provenance_sources(item: dict[str, Any]) -> list[dict[str, Any]]:
    sources = [item]
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        sources.append(attributes)
        for key in ["openabm", "runtime", "provenance"]:
            nested = attributes.get(key)
            if isinstance(nested, dict):
                sources.append(nested)
    runtime_context = item.get("runtime_context")
    if isinstance(runtime_context, dict):
        sources.append(runtime_context)
    return sources


def _runtime_provenance_value(item: dict[str, Any], key: str) -> str | None:
    for source in _runtime_provenance_sources(item):
        value = _optional_string(source.get(key))
        if value:
            return value
    return None


def _runtime_tool_version_ids(item: dict[str, Any]) -> list[str]:
    for source in _runtime_provenance_sources(item):
        values = _string_list(source.get("tool_version_ids"))
        if values:
            return sorted(set(values))
        value = _optional_string(source.get("tool_version_id"))
        if value:
            return [value]
    return []


def _trace_runtime_provenance(trace: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_version_id": _runtime_provenance_value(trace, "prompt_version_id"),
        "agent_config_version_id": _runtime_provenance_value(
            trace, "agent_config_version_id"
        ),
        "deployment_context_id": _runtime_provenance_value(trace, "deployment_context_id"),
        "tool_version_ids": _runtime_tool_version_ids(trace),
    }


def _eval_runtime_provenance(run: dict[str, Any]) -> dict[str, Any]:
    runtime_context = (
        run.get("runtime_context")
        if isinstance(run.get("runtime_context"), dict)
        else {}
    )
    payload = {
        **runtime_context,
        "prompt_version_id": run.get("prompt_version_id")
        or runtime_context.get("prompt_version_id"),
        "agent_config_version_id": run.get("agent_config_version_id")
        or runtime_context.get("agent_config_version_id"),
    }
    return {
        "prompt_version_id": _runtime_provenance_value(payload, "prompt_version_id"),
        "agent_config_version_id": _runtime_provenance_value(
            payload, "agent_config_version_id"
        ),
        "deployment_context_id": _runtime_provenance_value(payload, "deployment_context_id"),
        "tool_version_ids": _runtime_tool_version_ids(payload),
        "runtime_context": runtime_context,
    }


def _runtime_provenance_comparison(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    baseline_provenance = _eval_runtime_provenance(baseline)
    candidate_provenance = _eval_runtime_provenance(candidate)
    comparable_fields = [
        "prompt_version_id",
        "agent_config_version_id",
        "deployment_context_id",
        "tool_version_ids",
    ]
    changed_fields = [
        field
        for field in comparable_fields
        if baseline_provenance.get(field) != candidate_provenance.get(field)
    ]
    baseline_context = baseline_provenance.get("runtime_context") or {}
    candidate_context = candidate_provenance.get("runtime_context") or {}
    changed_context_keys = sorted(
        key
        for key in set(baseline_context) | set(candidate_context)
        if baseline_context.get(key) != candidate_context.get(key)
    )
    return {
        "baseline": baseline_provenance,
        "candidate": candidate_provenance,
        "changed_fields": changed_fields,
        "changed_runtime_context_keys": changed_context_keys,
    }


def _runtime_provenance_distribution(traces: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    distribution: dict[str, dict[str, int]] = {
        "prompt_version_id": {},
        "agent_config_version_id": {},
        "deployment_context_id": {},
        "tool_version_ids": {},
    }
    for trace in traces:
        provenance = _trace_runtime_provenance(trace)
        for key in ["prompt_version_id", "agent_config_version_id", "deployment_context_id"]:
            value = provenance.get(key)
            if isinstance(value, str) and value:
                distribution[key][value] = distribution[key].get(value, 0) + 1
        for tool_version_id in provenance["tool_version_ids"]:
            distribution["tool_version_ids"][tool_version_id] = (
                distribution["tool_version_ids"].get(tool_version_id, 0) + 1
            )
    return {key: values for key, values in distribution.items() if values}


def _differential_hypothesis(field: str, value: str) -> str:
    labels = {
        "status": "trace status",
        "span_status": "span status",
        "error_type": "error type",
        "tool_name": "tool usage",
        "prompt_version_id": "prompt version",
        "agent_config_version_id": "agent config version",
        "deployment_context_id": "deployment context",
        "tool_version_id": "tool version",
    }
    if field.startswith("dimension:"):
        labels[field] = f"business dimension {field.removeprefix('dimension:')}"
    return f"Failing cohort overrepresents {labels.get(field, field)}: {value}."


def _judge_promotion_blockers(
    report: dict[str, Any],
    review_tasks: list[dict[str, Any]],
    policy: dict[str, Any],
) -> list[str]:
    blockers = []
    min_score_count = int(policy.get("min_score_count", 1))
    if report["score_count"] < min_score_count:
        blockers.append("insufficient_eval_scores")
    invalid_rate = report.get("invalid_output_rate")
    if invalid_rate is None:
        blockers.append("missing_invalid_output_rate")
    elif invalid_rate > float(policy.get("max_invalid_output_rate", 0.0)):
        blockers.append("invalid_output_rate_too_high")
    if policy.get("require_accepted_review", True) and not report[
        "human_review_labels"
    ].get("accepted"):
        blockers.append("accepted_human_review_required")
    if policy.get("require_no_open_reviews", True) and any(
        task["status"] == "open" for task in review_tasks
    ):
        blockers.append("open_review_tasks")
    return blockers


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
            self._ensure_trace_provenance_columns(conn)
            self._ensure_eval_run_provenance_columns(conn)
            self._ensure_auth_api_key_columns(conn)
            self._ensure_automation_run_cooldown_columns(conn)
            self._ensure_mcp_tool_observation_payload_columns(conn)
            self._ensure_trace_span_resource_column(conn)
            self._ensure_score_failure_reason_column(conn)
            self.ensure_project("proj_demo", "Demo Project")

    @staticmethod
    def _ensure_trace_provenance_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(trace_metadata)").fetchall()
        }
        column_specs = {
            "prompt_version_id": "TEXT",
            "agent_config_version_id": "TEXT",
            "deployment_context_id": "TEXT",
            "tool_version_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for column, spec in column_specs.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE trace_metadata ADD COLUMN {column} {spec}")

    @staticmethod
    def _ensure_eval_run_provenance_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(eval_runs)").fetchall()
        }
        column_specs = {
            "agent_config_version_id": "TEXT",
            "runtime_context_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, spec in column_specs.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE eval_runs ADD COLUMN {column} {spec}")

    @staticmethod
    def _ensure_auth_api_key_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(api_keys)").fetchall()
        }
        column_specs = {
            "name": "TEXT",
            "actor_id": "TEXT",
            "actor_type": "TEXT",
            "role": "TEXT",
            "status": "TEXT",
            "last_used_at": "TEXT",
            "expires_at": "TEXT",
            "revoked_by": "TEXT",
            "updated_at": "TEXT",
        }
        for column, spec in column_specs.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE api_keys ADD COLUMN {column} {spec}")

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

    @staticmethod
    def _ensure_mcp_tool_observation_payload_columns(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(mcp_tool_observations)").fetchall()
        }
        column_specs = {
            "request_json": "TEXT NOT NULL DEFAULT '{}'",
            "response_json": "TEXT NOT NULL DEFAULT '{}'",
            "citations_json": "TEXT NOT NULL DEFAULT '[]'",
            "confirmation_required": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, spec in column_specs.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE mcp_tool_observations ADD COLUMN {column} {spec}")

    @staticmethod
    def _ensure_trace_span_resource_column(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(trace_spans)").fetchall()
        }
        if "resource_json" not in columns:
            conn.execute(
                "ALTER TABLE trace_spans ADD COLUMN resource_json TEXT NOT NULL DEFAULT '{}'"
            )

    @staticmethod
    def _ensure_score_failure_reason_column(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(scores)").fetchall()
        }
        if "failure_reason" not in columns:
            conn.execute("ALTER TABLE scores ADD COLUMN failure_reason TEXT")

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

    def ensure_auth_bootstrap(self, dev_api_key: str) -> None:
        self.ensure_project("proj_demo", "Demo Project")
        now = utc_now()
        key_hash = hash_secret(dev_api_key)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO orgs(org_id, name, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(org_id) DO UPDATE SET
                  name = excluded.name,
                  updated_at = excluded.updated_at
                """,
                (DEFAULT_ORG_ID, "Local Development Org", now, now),
            )
            conn.execute(
                """
                INSERT INTO auth_users(
                  user_id, email, display_name, auth_provider, external_subject,
                  status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                  email = excluded.email,
                  display_name = excluded.display_name,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    DEFAULT_OWNER_USER_ID,
                    "local-owner@openabm.dev",
                    "Local Owner",
                    "local",
                    DEFAULT_OWNER_USER_ID,
                    "active",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO project_memberships(
                  membership_id, org_id, project_id, user_id, role, status,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, user_id) DO UPDATE SET
                  role = excluded.role,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    "membership_local_owner_proj_demo",
                    DEFAULT_ORG_ID,
                    "proj_demo",
                    DEFAULT_OWNER_USER_ID,
                    "owner",
                    "active",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO service_accounts(
                  service_account_id, org_id, project_id, name, role, status,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_account_id) DO UPDATE SET
                  name = excluded.name,
                  role = excluded.role,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    DEFAULT_SERVICE_ACCOUNT_ID,
                    DEFAULT_ORG_ID,
                    "proj_demo",
                    "Local development API key",
                    "owner",
                    "active",
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO api_keys(
                  api_key_id, project_id, key_hash, scopes_json, revoked_at, created_at,
                  name, actor_id, actor_type, role, status, last_used_at, expires_at,
                  revoked_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(api_key_id) DO UPDATE SET
                  key_hash = excluded.key_hash,
                  name = excluded.name,
                  actor_id = excluded.actor_id,
                  actor_type = excluded.actor_type,
                  role = excluded.role,
                  scopes_json = excluded.scopes_json,
                  revoked_at = NULL,
                  revoked_by = NULL,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    DEFAULT_DEV_API_KEY_ID,
                    "proj_demo",
                    key_hash,
                    encode_json(["*"]),
                    None,
                    now,
                    "Local development owner key",
                    DEFAULT_SERVICE_ACCOUNT_ID,
                    "service_account",
                    "owner",
                    "active",
                    None,
                    None,
                    None,
                    now,
                ),
            )
            for record in _auth_decision_records(now):
                conn.execute(
                    """
                    INSERT INTO auth_decision_records(
                      record_id, topic, decision, rationale, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_id) DO UPDATE SET
                      decision = excluded.decision,
                      rationale = excluded.rationale,
                      status = excluded.status,
                      updated_at = excluded.updated_at
                    """,
                    (
                        record["record_id"],
                        record["topic"],
                        record["decision"],
                        record["rationale"],
                        record["status"],
                        now,
                        now,
                    ),
                )

    def authenticate_api_key(self, api_key: str) -> dict[str, Any] | None:
        key_hash = hash_secret(api_key)
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
            if row is None:
                return None
            item = self._api_key_from_row(row, include_hash=False)
            if item["status"] != "active" or item.get("revoked_at") is not None:
                return None
            expires_at = item.get("expires_at")
            if isinstance(expires_at, str) and expires_at:
                parsed = _parse_utc_datetime(expires_at)
                if parsed is not None and parsed < datetime.now(UTC):
                    return None
            conn.execute(
                """
                UPDATE api_keys
                SET last_used_at = ?, updated_at = ?
                WHERE api_key_id = ?
                """,
                (now, now, item["api_key_id"]),
            )
        return {**item, "last_used_at": now}

    def list_api_keys(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM api_keys
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._api_key_from_row(row, include_hash=False) for row in rows]

    def create_api_key(
        self,
        request: dict[str, Any],
        *,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        project_id = request["project_id"]
        self.ensure_project(project_id)
        now = utc_now()
        role = _auth_role(request.get("role"), "viewer")
        actor_type = str(request.get("actor_type") or "service_account")
        actor_ref = request.get("actor_id") or new_id("service_account")
        scopes = _string_list(request.get("scopes")) or ["*"]
        api_key = f"opabm_{secrets.token_urlsafe(32)}"
        item = {
            "api_key_id": new_id("api_key"),
            "project_id": project_id,
            "name": request.get("name") or f"{role.title()} API key",
            "actor_id": str(actor_ref),
            "actor_type": actor_type,
            "role": role,
            "scopes": scopes,
            "status": "active",
            "last_used_at": None,
            "expires_at": request.get("expires_at"),
            "revoked_at": None,
            "revoked_by": None,
            "created_at": now,
            "updated_at": now,
        }
        if actor_type == "service_account":
            self.ensure_service_account(
                project_id=project_id,
                service_account_id=item["actor_id"],
                name=item["name"],
                role=role,
            )
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys(
                  api_key_id, project_id, key_hash, scopes_json, revoked_at, created_at,
                  name, actor_id, actor_type, role, status, last_used_at, expires_at,
                  revoked_by, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["api_key_id"],
                    item["project_id"],
                    hash_secret(api_key),
                    encode_json(scopes),
                    None,
                    now,
                    item["name"],
                    item["actor_id"],
                    item["actor_type"],
                    item["role"],
                    item["status"],
                    None,
                    item["expires_at"],
                    None,
                    now,
                ),
            )
        self.append_audit(
            "create_api_key",
            "api_key",
            project_id,
            item["api_key_id"],
            {"role": role, "scopes": scopes, "actor_type": actor_type},
            actor_id=actor_id,
        )
        return {**item, "api_key": api_key}

    def revoke_api_key(
        self,
        project_id: str,
        api_key_id: str,
        *,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE api_keys
                SET revoked_at = ?, revoked_by = ?, status = ?, updated_at = ?
                WHERE project_id = ? AND api_key_id = ?
                """,
                (now, actor_id, "revoked", now, project_id, api_key_id),
            )
            row = conn.execute(
                "SELECT * FROM api_keys WHERE project_id = ? AND api_key_id = ?",
                (project_id, api_key_id),
            ).fetchone()
        if row is None:
            raise KeyError("API key not found")
        item = self._api_key_from_row(row, include_hash=False)
        self.append_audit(
            "revoke_api_key",
            "api_key",
            project_id,
            api_key_id,
            {"revoked_at": now},
            actor_id=actor_id,
        )
        return item

    def ensure_service_account(
        self,
        *,
        project_id: str,
        service_account_id: str,
        name: str,
        role: str,
    ) -> dict[str, Any]:
        now = utc_now()
        role = _auth_role(role, "viewer")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO service_accounts(
                  service_account_id, org_id, project_id, name, role, status,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(service_account_id) DO UPDATE SET
                  name = excluded.name,
                  role = excluded.role,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    service_account_id,
                    DEFAULT_ORG_ID,
                    project_id,
                    name,
                    role,
                    "active",
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM service_accounts WHERE service_account_id = ?",
                (service_account_id,),
            ).fetchone()
        return self._service_account_from_row(row)

    def list_auth_users(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT u.*, m.membership_id, m.role, m.status AS membership_status
                FROM auth_users u
                LEFT JOIN project_memberships m ON m.user_id = u.user_id
                WHERE m.project_id = ?
                ORDER BY u.email ASC
                """,
                (project_id,),
            ).fetchall()
        return [self._auth_user_from_row(row) for row in rows]

    def create_auth_user(self, request: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        user_id = request.get("user_id") or new_id("user")
        email = str(request["email"]).strip().lower()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_users(
                  user_id, email, display_name, auth_provider, external_subject,
                  status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                  display_name = excluded.display_name,
                  auth_provider = excluded.auth_provider,
                  external_subject = excluded.external_subject,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    email,
                    request.get("display_name"),
                    request.get("auth_provider") or "local",
                    request.get("external_subject"),
                    request.get("status") or "active",
                    now,
                    now,
                ),
            )
            row = conn.execute("SELECT * FROM auth_users WHERE email = ?", (email,)).fetchone()
        return self._auth_user_from_row(row)

    def list_project_memberships(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.*, u.email, u.display_name
                FROM project_memberships m
                JOIN auth_users u ON u.user_id = m.user_id
                WHERE m.project_id = ?
                ORDER BY m.created_at ASC
                """,
                (project_id,),
            ).fetchall()
        return [self._membership_from_row(row) for row in rows]

    def upsert_project_membership(self, request: dict[str, Any]) -> dict[str, Any]:
        project_id = request["project_id"]
        user_id = request["user_id"]
        role = _auth_role(request.get("role"), "viewer")
        now = utc_now()
        with self.connect() as conn:
            user = conn.execute("SELECT * FROM auth_users WHERE user_id = ?", (user_id,)).fetchone()
            if user is None:
                raise KeyError("Auth user not found")
            conn.execute(
                """
                INSERT INTO project_memberships(
                  membership_id, org_id, project_id, user_id, role, status,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, user_id) DO UPDATE SET
                  role = excluded.role,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    request.get("membership_id") or new_id("membership"),
                    request.get("org_id") or DEFAULT_ORG_ID,
                    project_id,
                    user_id,
                    role,
                    request.get("status") or "active",
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT m.*, u.email, u.display_name
                FROM project_memberships m
                JOIN auth_users u ON u.user_id = m.user_id
                WHERE m.project_id = ? AND m.user_id = ?
                """,
                (project_id, user_id),
            ).fetchone()
        return self._membership_from_row(row)

    def list_auth_invites(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM auth_invites
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
            delivery_rows = conn.execute(
                """
                SELECT * FROM auth_invite_deliveries
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        deliveries_by_invite: dict[str, list[dict[str, Any]]] = {}
        for row in delivery_rows:
            delivery = self._invite_delivery_from_row(row)
            deliveries_by_invite.setdefault(delivery["invite_id"], []).append(delivery)
        invites = [self._invite_from_row(row) for row in rows]
        for invite in invites:
            deliveries = deliveries_by_invite.get(invite["invite_id"], [])
            if deliveries:
                invite["delivery"] = deliveries[0]
                invite["deliveries"] = deliveries
        return invites

    def create_auth_invite(
        self,
        request: dict[str, Any],
        *,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        expires_in_seconds = int(request.get("expires_in_seconds") or 7 * 24 * 60 * 60)
        item = {
            "invite_id": new_id("invite"),
            "org_id": request.get("org_id") or DEFAULT_ORG_ID,
            "project_id": request["project_id"],
            "email": str(request["email"]).strip().lower(),
            "role": _auth_role(request.get("role"), "viewer"),
            "status": "pending",
            "invited_by": actor_id,
            "expires_at": request.get("expires_at") or _future_timestamp(expires_in_seconds),
            "accepted_at": None,
            "created_at": now,
            "updated_at": now,
        }
        should_queue_delivery = not bool(request.get("suppress_delivery"))
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO auth_invites(
                  invite_id, org_id, project_id, email, role, status, invited_by,
                  expires_at, accepted_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["invite_id"],
                    item["org_id"],
                    item["project_id"],
                    item["email"],
                    item["role"],
                    item["status"],
                    item["invited_by"],
                    item["expires_at"],
                    item["accepted_at"],
                    item["created_at"],
                    item["updated_at"],
                ),
            )
            delivery = None
            if should_queue_delivery:
                delivery = self._create_auth_invite_delivery_row(conn, item)
        self.append_audit(
            "create_auth_invite",
            "auth_invite",
            item["project_id"],
            item["invite_id"],
            {"email": item["email"], "role": item["role"]},
            actor_id=actor_id,
        )
        if delivery is not None:
            self.append_audit(
                "queue_auth_invite_delivery",
                "auth_invite",
                item["project_id"],
                item["invite_id"],
                {
                    "invite_delivery_id": delivery["invite_delivery_id"],
                    "delivery_channel": delivery["delivery_channel"],
                    "delivery_status": delivery["delivery_status"],
                },
                actor_id=actor_id,
            )
            item["delivery"] = delivery
        return item

    def list_auth_invite_deliveries(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM auth_invite_deliveries
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._invite_delivery_from_row(row) for row in rows]

    def _create_auth_invite_delivery_row(
        self,
        conn: sqlite3.Connection,
        invite: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        payload = {
            "template": "auth_invite_v1",
            "invite_id": invite["invite_id"],
            "project_id": invite["project_id"],
            "email": invite["email"],
            "role": invite["role"],
            "expires_at": invite["expires_at"],
        }
        delivery = {
            "invite_delivery_id": new_id("invite_delivery"),
            "invite_id": invite["invite_id"],
            "project_id": invite["project_id"],
            "delivery_channel": "local_outbox",
            "delivery_status": "queued",
            "recipient_email": invite["email"],
            "payload": payload,
            "error_nullable": None,
            "created_at": now,
            "updated_at": now,
        }
        conn.execute(
            """
            INSERT INTO auth_invite_deliveries(
              invite_delivery_id, invite_id, project_id, delivery_channel,
              delivery_status, recipient_email, payload_json, error_nullable,
              created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                delivery["invite_delivery_id"],
                delivery["invite_id"],
                delivery["project_id"],
                delivery["delivery_channel"],
                delivery["delivery_status"],
                delivery["recipient_email"],
                encode_json(delivery["payload"]),
                delivery["error_nullable"],
                delivery["created_at"],
                delivery["updated_at"],
            ),
        )
        return delivery

    def list_auth_sessions(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.*, u.email, u.display_name
                FROM auth_sessions s
                JOIN auth_users u ON u.user_id = s.user_id
                WHERE s.project_id = ?
                ORDER BY s.created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._auth_session_from_row(row, include_hashes=False) for row in rows]

    def create_auth_session(
        self,
        request: dict[str, Any],
        *,
        cookie_policy: dict[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        ttl_seconds = int(request.get("ttl_seconds") or 7 * 24 * 60 * 60)
        session_token = f"opabm_sess_{secrets.token_urlsafe(32)}"
        csrf_token = f"opabm_csrf_{secrets.token_urlsafe(24)}"
        item = {
            "auth_session_id": new_id("auth_session"),
            "user_id": request["user_id"],
            "org_id": request.get("org_id") or DEFAULT_ORG_ID,
            "project_id": request["project_id"],
            "cookie_policy": cookie_policy,
            "ip_hint": request.get("ip_hint"),
            "user_agent_hint": request.get("user_agent_hint"),
            "status": "active",
            "expires_at": request.get("expires_at") or _future_timestamp(ttl_seconds),
            "revoked_at": None,
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            user = conn.execute(
                "SELECT * FROM auth_users WHERE user_id = ?",
                (item["user_id"],),
            ).fetchone()
            if user is None:
                raise KeyError("Auth user not found")
            conn.execute(
                """
                INSERT INTO auth_sessions(
                  auth_session_id, user_id, org_id, project_id, session_token_hash,
                  csrf_token_hash, cookie_policy_json, ip_hint, user_agent_hint,
                  status, expires_at, revoked_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["auth_session_id"],
                    item["user_id"],
                    item["org_id"],
                    item["project_id"],
                    hash_secret(session_token),
                    hash_secret(csrf_token),
                    encode_json(cookie_policy),
                    item["ip_hint"],
                    item["user_agent_hint"],
                    item["status"],
                    item["expires_at"],
                    None,
                    now,
                    now,
                ),
            )
        return {**item, "session_token": session_token, "csrf_token": csrf_token}

    def revoke_auth_session(self, project_id: str, auth_session_id: str) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE auth_sessions
                SET status = ?, revoked_at = ?, updated_at = ?
                WHERE project_id = ? AND auth_session_id = ?
                """,
                ("revoked", now, now, project_id, auth_session_id),
            )
            row = conn.execute(
                """
                SELECT s.*, u.email, u.display_name
                FROM auth_sessions s
                JOIN auth_users u ON u.user_id = s.user_id
                WHERE s.project_id = ? AND s.auth_session_id = ?
                """,
                (project_id, auth_session_id),
            ).fetchone()
        if row is None:
            raise KeyError("Auth session not found")
        return self._auth_session_from_row(row, include_hashes=False)

    def list_auth_decision_records(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM auth_decision_records ORDER BY topic ASC"
            ).fetchall()
        return [self._auth_decision_from_row(row) for row in rows]

    def list_secret_refs(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM secret_refs
                WHERE project_id = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._secret_ref_from_row(row, include_ciphertext=False) for row in rows]

    def get_secret_ref(
        self,
        project_id: str,
        secret_ref: str,
        *,
        include_ciphertext: bool = False,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM secret_refs
                WHERE project_id = ? AND secret_ref = ? AND deleted_at IS NULL
                """,
                (project_id, secret_ref),
            ).fetchone()
        if row is None:
            return None
        return self._secret_ref_from_row(row, include_ciphertext=include_ciphertext)

    def create_secret_ref(
        self,
        request: dict[str, Any],
        *,
        ciphertext: str,
        ciphertext_sha256: str,
        encryption_mode: str,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        project_id = request["project_id"]
        self.ensure_project(project_id)
        now = utc_now()
        secret_ref = request.get("secret_ref") or f"secret_{secrets.token_urlsafe(18)}"
        item = {
            "secret_ref": secret_ref,
            "org_id": request.get("org_id") or DEFAULT_ORG_ID,
            "project_id": project_id,
            "purpose": request["purpose"],
            "provider": request.get("provider") or "local",
            "status": request.get("status") or "active",
            "current_version": 1,
            "encryption_mode": encryption_mode,
            "ciphertext": ciphertext,
            "ciphertext_sha256": ciphertext_sha256,
            "rotation_due_at": request.get("rotation_due_at"),
            "rotated_at": None,
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO secret_refs(
                  secret_ref, org_id, project_id, purpose, provider, status,
                  current_version, encryption_mode, ciphertext, ciphertext_sha256,
                  rotation_due_at, rotated_at, created_at, updated_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["secret_ref"],
                    item["org_id"],
                    item["project_id"],
                    item["purpose"],
                    item["provider"],
                    item["status"],
                    item["current_version"],
                    item["encryption_mode"],
                    item["ciphertext"],
                    item["ciphertext_sha256"],
                    item["rotation_due_at"],
                    item["rotated_at"],
                    item["created_at"],
                    item["updated_at"],
                    None,
                ),
            )
            conn.execute(
                """
                INSERT INTO secret_versions(
                  secret_version_id, secret_ref, project_id, version, encryption_mode,
                  ciphertext, ciphertext_sha256, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("secret_version"),
                    item["secret_ref"],
                    project_id,
                    1,
                    encryption_mode,
                    ciphertext,
                    ciphertext_sha256,
                    now,
                ),
            )
        self.append_audit(
            "create_secret_ref",
            "secret_ref",
            project_id,
            item["secret_ref"],
            {"purpose": item["purpose"], "provider": item["provider"]},
            actor_id=actor_id,
        )
        self.append_secret_access(
            project_id,
            item["secret_ref"],
            action="create",
            purpose=item["purpose"],
            actor_id=actor_id,
        )
        return {key: value for key, value in item.items() if key != "ciphertext"}

    def rotate_secret_ref(
        self,
        project_id: str,
        secret_ref: str,
        *,
        ciphertext: str,
        ciphertext_sha256: str,
        encryption_mode: str,
        rotation_due_at: str | None = None,
        actor_id: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM secret_refs
                WHERE project_id = ? AND secret_ref = ? AND deleted_at IS NULL
                """,
                (project_id, secret_ref),
            ).fetchone()
            if row is None:
                raise KeyError("Secret ref not found")
            next_version = int(row["current_version"]) + 1
            conn.execute(
                """
                UPDATE secret_refs
                SET current_version = ?, encryption_mode = ?, ciphertext = ?,
                    ciphertext_sha256 = ?, rotation_due_at = ?, rotated_at = ?,
                    updated_at = ?
                WHERE project_id = ? AND secret_ref = ?
                """,
                (
                    next_version,
                    encryption_mode,
                    ciphertext,
                    ciphertext_sha256,
                    rotation_due_at,
                    now,
                    now,
                    project_id,
                    secret_ref,
                ),
            )
            conn.execute(
                """
                INSERT INTO secret_versions(
                  secret_version_id, secret_ref, project_id, version, encryption_mode,
                  ciphertext, ciphertext_sha256, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id("secret_version"),
                    secret_ref,
                    project_id,
                    next_version,
                    encryption_mode,
                    ciphertext,
                    ciphertext_sha256,
                    now,
                ),
            )
            updated = conn.execute(
                "SELECT * FROM secret_refs WHERE project_id = ? AND secret_ref = ?",
                (project_id, secret_ref),
            ).fetchone()
        self.append_audit(
            "rotate_secret_ref",
            "secret_ref",
            project_id,
            secret_ref,
            {"current_version": next_version},
            actor_id=actor_id,
        )
        self.append_secret_access(
            project_id,
            secret_ref,
            action="rotate",
            purpose=row["purpose"],
            actor_id=actor_id,
        )
        return self._secret_ref_from_row(updated, include_ciphertext=False)

    def append_secret_access(
        self,
        project_id: str,
        secret_ref: str,
        *,
        action: str,
        purpose: str | None = None,
        actor_id: str | None = None,
    ) -> str:
        access_id = new_id("secret_access")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO secret_access_log(
                  secret_access_id, project_id, secret_ref, actor_id, action, purpose, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (access_id, project_id, secret_ref, actor_id, action, purpose, utc_now()),
            )
        return access_id

    def list_secret_access_log(self, project_id: str, secret_ref: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM secret_access_log
                WHERE project_id = ? AND secret_ref = ?
                ORDER BY created_at DESC
                """,
                (project_id, secret_ref),
            ).fetchall()
        return [self._secret_access_from_row(row) for row in rows]

    def record_worker_heartbeat(self, request: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        item = {
            "worker_id": request.get("worker_id") or "local-reference-worker",
            "project_id": request.get("project_id"),
            "worker_type": request.get("worker_type") or "local",
            "status": request.get("status") or "ok",
            "queue_depth": _non_negative_int(request.get("queue_depth")),
            "details": request.get("details") or {},
            "last_seen_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO worker_heartbeats(
                  worker_id, project_id, worker_type, status, queue_depth,
                  details_json, last_seen_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(worker_id) DO UPDATE SET
                  project_id = excluded.project_id,
                  worker_type = excluded.worker_type,
                  status = excluded.status,
                  queue_depth = excluded.queue_depth,
                  details_json = excluded.details_json,
                  last_seen_at = excluded.last_seen_at
                """,
                (
                    item["worker_id"],
                    item["project_id"],
                    item["worker_type"],
                    item["status"],
                    item["queue_depth"],
                    encode_json(item["details"]),
                    now,
                ),
            )
        return item

    def list_worker_heartbeats(self, project_id: str | None = None) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if project_id:
            clauses.append("(project_id = ? OR project_id IS NULL)")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM worker_heartbeats
                {where}
                ORDER BY last_seen_at DESC
                """,
                params,
            ).fetchall()
        return [self._worker_heartbeat_from_row(row) for row in rows]

    def list_dead_letter_runs(self, project_id: str, limit: int = 25) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM automation_runs
                WHERE project_id = ?
                  AND status IN ('dead_lettered', 'partial_failure')
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (project_id, max(1, min(limit, 100))),
            ).fetchall()
        return [self._automation_run_from_row(row) for row in rows]

    def record_mcp_tool_observation(self, request: dict[str, Any]) -> dict[str, Any]:
        item = {
            "observation_id": request.get("observation_id") or new_id("mcp_tool_observation"),
            "project_id": request.get("project_id"),
            "tool_name": request["tool_name"],
            "status": request.get("status") or "succeeded",
            "latency_ms": _non_negative_int(request.get("latency_ms")),
            "request": request.get("request") or {},
            "response": request.get("response") or {},
            "citations": request.get("citations") or [],
            "confirmation_required": bool(request.get("confirmation_required")),
            "error_type_nullable": request.get("error_type_nullable"),
            "error_message_nullable": request.get("error_message_nullable"),
            "created_at": utc_now(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO mcp_tool_observations(
                  observation_id, project_id, tool_name, status, latency_ms,
                  request_json, response_json, citations_json, confirmation_required,
                  error_type_nullable, error_message_nullable, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["observation_id"],
                    item["project_id"],
                    item["tool_name"],
                    item["status"],
                    item["latency_ms"],
                    encode_json(item["request"]),
                    encode_json(item["response"]),
                    encode_json(item["citations"]),
                    int(item["confirmation_required"]),
                    item["error_type_nullable"],
                    item["error_message_nullable"],
                    item["created_at"],
                ),
            )
        return item

    def list_mcp_tool_observations(
        self,
        project_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if project_id:
                rows = conn.execute(
                    """
                    SELECT * FROM mcp_tool_observations
                    WHERE project_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (project_id, max(1, min(limit, 200))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM mcp_tool_observations
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (max(1, min(limit, 200)),),
                ).fetchall()
        return [self._mcp_tool_observation_from_row(row) for row in rows]

    @staticmethod
    def _mcp_tool_observation_from_row(row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        item["request"] = decode_json(item.pop("request_json", None), {})
        item["response"] = decode_json(item.pop("response_json", None), {})
        item["citations"] = decode_json(item.pop("citations_json", None), [])
        item["confirmation_required"] = bool(item.get("confirmation_required"))
        return item

    def mcp_tool_observability_summary(self, project_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT tool_name,
                       COUNT(*) AS call_count,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS error_count,
                       AVG(latency_ms) AS avg_latency_ms,
                       MAX(latency_ms) AS max_latency_ms
                FROM mcp_tool_observations
                WHERE project_id = ?
                GROUP BY tool_name
                ORDER BY call_count DESC, tool_name ASC
                """,
                (project_id,),
            ).fetchall()
        tools = [
            {
                "tool_name": row["tool_name"],
                "call_count": int(row["call_count"]),
                "error_count": int(row["error_count"]),
                "avg_latency_ms": float(row["avg_latency_ms"] or 0),
                "max_latency_ms": int(row["max_latency_ms"] or 0),
            }
            for row in rows
        ]
        return {
            "total_calls": sum(tool["call_count"] for tool in tools),
            "error_count": sum(tool["error_count"] for tool in tools),
            "tools": tools,
        }

    def ops_status(self, project_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            storage_counts = {
                table: self._table_count(conn, table, project_id)
                for table in [
                    "trace_metadata",
                    "trace_spans",
                    "scores",
                    "behavior_matches",
                    "datasets",
                    "dataset_examples",
                    "eval_runs",
                    "eval_results",
                    "issues",
                    "investigation_runs",
                    "impact_reports",
                    "agent_context_packs",
                    "review_tasks",
                    "automation_runs",
                    "secret_refs",
                    "mcp_tool_observations",
                    "audit_log",
                ]
            }
            payload_growth = conn.execute(
                """
                SELECT COUNT(*) AS count,
                       COALESCE(SUM(byte_size_nullable), 0) AS total_bytes
                FROM payload_objects
                WHERE project_id = ? AND deleted_at IS NULL
                """,
                (project_id,),
            ).fetchone()
            open_reviews = conn.execute(
                """
                SELECT COUNT(*) AS count FROM review_tasks
                WHERE project_id = ? AND status = 'open'
                """,
                (project_id,),
            ).fetchone()
            automation_failures = conn.execute(
                """
                SELECT COUNT(*) AS count FROM automation_runs
                WHERE project_id = ?
                  AND status IN ('dead_lettered', 'partial_failure')
                """,
                (project_id,),
            ).fetchone()
            latest_retention = conn.execute(
                """
                SELECT action, target_id, metadata_json, created_at
                FROM audit_log
                WHERE project_id = ? AND action = 'apply_retention_policy'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (project_id,),
            ).fetchone()
        generated_at = utc_now()
        worker_heartbeats = self.list_worker_heartbeats(project_id)
        worker_health = _worker_heartbeat_health(worker_heartbeats, now=generated_at)
        worker_queue_depth = sum(int(item["queue_depth"]) for item in worker_heartbeats)
        mcp_tool_observability = self.mcp_tool_observability_summary(project_id)
        return {
            "project_id": project_id,
            "generated_at": generated_at,
            "storage_growth": storage_counts,
            "payload_store_growth": {
                "object_count": int(payload_growth["count"]),
                "total_bytes": int(payload_growth["total_bytes"]),
            },
            "queue_depth": {
                "open_review_tasks": int(open_reviews["count"]),
                "worker_jobs": worker_queue_depth,
            },
            "retention_job_status": dict(latest_retention) if latest_retention else None,
            "automation_action_failures": int(automation_failures["count"]),
            "dead_letter_count": int(automation_failures["count"]),
            "worker_heartbeats": worker_heartbeats,
            "worker_health": worker_health,
            "stale_worker_count": sum(
                1 for item in worker_health if item["status"] in {"stale", "unhealthy"}
            ),
            "mcp_tool_observability": mcp_tool_observability,
        }

    @staticmethod
    def _table_count(conn: sqlite3.Connection, table: str, project_id: str) -> int:
        row = conn.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return int(row["count"])

    def upsert_trace(self, trace: dict[str, Any]) -> str:
        now = utc_now()
        self.ensure_project(trace["project_id"])
        provenance = _trace_runtime_provenance(trace)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO trace_metadata(
                  trace_id, project_id, session_id, user_external_id, root_span_id,
                  environment, status, started_at, ended_at, tags_json, attributes_json,
                  prompt_version_id, agent_config_version_id, deployment_context_id,
                  tool_version_ids_json, summary, server_received_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                  prompt_version_id = excluded.prompt_version_id,
                  agent_config_version_id = excluded.agent_config_version_id,
                  deployment_context_id = excluded.deployment_context_id,
                  tool_version_ids_json = excluded.tool_version_ids_json,
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
                    provenance["prompt_version_id"],
                    provenance["agent_config_version_id"],
                    provenance["deployment_context_id"],
                    encode_json(provenance["tool_version_ids"]),
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
                  resource_json, events_json, links_json, server_received_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                  resource_json = excluded.resource_json,
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
                    encode_json(span.get("resource", {})),
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
        if filters.get("prompt_version_id"):
            clauses.append("prompt_version_id = ?")
            params.append(filters["prompt_version_id"])
        if filters.get("agent_config_version_id"):
            clauses.append("agent_config_version_id = ?")
            params.append(filters["agent_config_version_id"])
        if filters.get("deployment_context_id"):
            clauses.append("deployment_context_id = ?")
            params.append(filters["deployment_context_id"])
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

    def list_behavior_matches(
        self,
        project_id: str,
        trace_id: str | None = None,
        behavior_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if trace_id:
            clauses.append("trace_id = ?")
            params.append(trace_id)
        if behavior_id:
            clauses.append("behavior_id = ?")
            params.append(behavior_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM behavior_matches WHERE "
                + " AND ".join(clauses)
                + " ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._behavior_match_from_row(row) for row in rows]

    def label_trace_behavior(
        self,
        project_id: str,
        trace_id: str,
        behavior_id: str,
        span_id: str | None = None,
    ) -> dict[str, Any]:
        trace = self.get_trace(project_id, trace_id)
        if trace is None:
            raise KeyError(f"trace not found: {trace_id}")
        attributes = dict(trace.get("attributes") or {})
        behavior_ids = _string_list(attributes.get("openabm.behavior_ids"))
        if behavior_id not in behavior_ids:
            behavior_ids.append(behavior_id)
        trace["attributes"] = {**attributes, "openabm.behavior_ids": behavior_ids}
        self.upsert_trace(trace)

        now = utc_now()
        evidence_span_ids = [span_id] if span_id else []
        match = {
            "behavior_match_id": new_id("behavior_match"),
            "project_id": project_id,
            "behavior_id": behavior_id,
            "trace_id": trace_id,
            "span_id": span_id,
            "score_id": None,
            "status": "confirmed",
            "evidence_span_ids": evidence_span_ids,
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                DELETE FROM behavior_matches
                WHERE project_id = ? AND trace_id = ? AND behavior_id = ?
                  AND status = 'confirmed'
                """,
                (project_id, trace_id, behavior_id),
            )
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
                    project_id,
                    behavior_id,
                    trace_id,
                    span_id,
                    None,
                    "confirmed",
                    encode_json(evidence_span_ids),
                    now,
                ),
            )
        return {"trace": self.get_trace(project_id, trace_id), "behavior_match": match}

    def record_score(self, project_id: str, score: dict[str, Any]) -> dict[str, Any]:
        self.ensure_project(project_id)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO scores(
                  score_id, project_id, trace_id, span_id, judge_id,
                  judge_version_id, status, failure_reason, value_json, confidence, reasoning,
                  evidence_span_ids_json, failure_mode, cost_json, latency_ms,
                  created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    score["score_id"],
                    project_id,
                    score["trace_id"],
                    score.get("span_id"),
                    score["judge_id"],
                    score.get("judge_version_id"),
                    score["status"],
                    score.get("failure_reason"),
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
        agent_config_version_id: str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_project(project_id)
        now = utc_now()
        runtime_context = runtime_context or {}
        item = {
            "eval_run_id": new_id("eval_run"),
            "project_id": project_id,
            "dataset_version_id": dataset_version_id,
            "baseline_eval_run_id": baseline_eval_run_id,
            "runner": runner,
            "judges": judges,
            "prompt_version_id": prompt_version_id,
            "agent_config_version_id": agent_config_version_id,
            "runtime_context": runtime_context,
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
                  runner_json, judges_json, prompt_version_id, agent_config_version_id,
                  runtime_context_json, status, summary_json, created_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["eval_run_id"],
                    project_id,
                    dataset_version_id,
                    baseline_eval_run_id,
                    encode_json(runner),
                    encode_json(judges),
                    prompt_version_id,
                    agent_config_version_id,
                    encode_json(runtime_context),
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

    def eval_run_analytics(self, project_id: str) -> dict[str, Any]:
        runs = self.list_eval_runs(project_id)
        return {
            "project_id": project_id,
            "run_count": len(runs),
            "by_prompt_version": _group_eval_runs(
                runs,
                lambda run: run.get("prompt_version_id") or "unversioned",
            ),
            "by_agent_config_version": _group_eval_runs(
                runs,
                lambda run: run.get("agent_config_version_id") or "unversioned",
            ),
            "by_deployment_context": _group_eval_runs(
                runs,
                lambda run: str(
                    (run.get("runtime_context") or {}).get("deployment_context_id")
                    or "unversioned"
                ),
            ),
            "recent_runs": [
                {
                    "eval_run_id": run["eval_run_id"],
                    "dataset_version_id": run["dataset_version_id"],
                    "status": run["status"],
                    "prompt_version_id": run.get("prompt_version_id"),
                    "agent_config_version_id": run.get("agent_config_version_id"),
                    "deployment_context_id": (run.get("runtime_context") or {}).get(
                        "deployment_context_id"
                    ),
                    "pass_rate": _pass_rate(run.get("summary", {})),
                    "invalid_output_count": _invalid_output_count(run.get("summary", {})),
                    "created_at": run["created_at"],
                    "completed_at": run.get("completed_at"),
                }
                for run in runs[:10]
            ],
        }

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
            "provenance_comparison": _runtime_provenance_comparison(baseline, candidate),
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

    def promote_judge(
        self,
        project_id: str,
        judge_id: str,
        *,
        policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = {
            "min_score_count": 1,
            "max_invalid_output_rate": 0.0,
            "require_accepted_review": True,
            "require_no_open_reviews": True,
            **(policy or {}),
        }
        report = self.build_judge_calibration_report(project_id, judge_id)
        blockers = _judge_promotion_blockers(
            report,
            self._judge_review_tasks(project_id, judge_id),
            policy,
        )
        if blockers:
            return {
                "status": "blocked",
                "judge_id": judge_id,
                "project_id": project_id,
                "promotion_policy": policy,
                "blocking_reasons": blockers,
                "calibration_report": report,
            }
        judge = self._update_judge_status(project_id, judge_id, "active")
        return {
            "status": "promoted",
            "judge": judge,
            "promotion_policy": policy,
            "blocking_reasons": [],
            "calibration_report": report,
        }

    def _judge_review_tasks(self, project_id: str, judge_id: str) -> list[dict[str, Any]]:
        return [
            task
            for task in self.list_review_tasks(project_id, task_type="judge_output")
            if task["source_entity_id"] == judge_id
        ]

    def _update_judge_status(
        self,
        project_id: str,
        judge_id: str,
        status: str,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE judges
                SET status = ?, updated_at = ?
                WHERE project_id = ? AND judge_id = ?
                """,
                (status, now, project_id, judge_id),
            )
        judge = self.get_judge(project_id, judge_id)
        if judge is None:
            raise KeyError(f"judge not found: {judge_id}")
        return judge

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

    def create_issue_link(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        project_id = request["project_id"]
        issue_id = request["issue_id"]
        if self.get_issue(project_id, issue_id) is None:
            raise KeyError(f"issue not found: {issue_id}")
        now = utc_now()
        item = {
            "issue_link_id": new_id("issue_link"),
            "project_id": project_id,
            "issue_id": issue_id,
            "target_type": request["target_type"],
            "target_id": request["target_id"],
            "relation": request.get("relation", "related_to"),
            "source": request.get("source", "manual"),
            "evidence_trace_ids": request.get("evidence_trace_ids") or [],
            "evidence_span_ids": request.get("evidence_span_ids") or [],
            "metadata": request.get("metadata") or {},
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO issue_links(
                  issue_link_id, project_id, issue_id, target_type, target_id,
                  relation, source, evidence_trace_ids_json, evidence_span_ids_json,
                  metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["issue_link_id"],
                    project_id,
                    issue_id,
                    item["target_type"],
                    item["target_id"],
                    item["relation"],
                    item["source"],
                    encode_json(item["evidence_trace_ids"]),
                    encode_json(item["evidence_span_ids"]),
                    encode_json(item["metadata"]),
                    now,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM issue_links
                WHERE project_id = ? AND issue_id = ? AND target_type = ?
                  AND target_id = ? AND relation = ?
                """,
                (
                    project_id,
                    issue_id,
                    item["target_type"],
                    item["target_id"],
                    item["relation"],
                ),
            ).fetchone()
        if row is None:
            raise KeyError("issue link was not persisted")
        return self._issue_link_from_row(row)

    def list_issue_links(self, project_id: str, issue_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM issue_links
                WHERE project_id = ? AND issue_id = ?
                ORDER BY created_at ASC
                """,
                (project_id, issue_id),
            ).fetchall()
        return [self._issue_link_from_row(row) for row in rows]

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

    def get_retention_policy(
        self,
        project_id: str,
        retention_policy_id: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM retention_policies
                WHERE project_id = ? AND retention_policy_id = ?
                """,
                (project_id, retention_policy_id),
            ).fetchone()
        return self._retention_policy_from_row(row) if row else None

    def apply_retention_policy(
        self,
        project_id: str,
        retention_policy_id: str,
        *,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        policy = self.get_retention_policy(project_id, retention_policy_id)
        if policy is None:
            raise KeyError(f"retention policy not found: {retention_policy_id}")
        if not dry_run and policy["status"] != "active":
            raise ValueError("Only active retention policies can be applied.")
        now = utc_now()
        candidate_trace_ids = _retention_trace_candidates(
            self.search_traces(project_id, limit=10000),
            policy["rules"],
            now=now,
        )
        effects = []
        if not dry_run:
            effects = [
                self.tombstone_trace(project_id, trace_id)
                for trace_id in candidate_trace_ids
            ]
        return {
            "retention_policy_id": retention_policy_id,
            "project_id": project_id,
            "dry_run": dry_run,
            "status": "planned" if dry_run else "applied",
            "evaluated_rules": policy["rules"],
            "candidate_trace_ids": candidate_trace_ids,
            "deleted_trace_ids": [effect["trace_id"] for effect in effects],
            "effects": effects,
            "created_at": now,
        }

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

    def list_automation_runs(
        self,
        project_id: str,
        automation_id: str,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM automation_runs
                WHERE project_id = ? AND automation_id = ?
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (project_id, automation_id, limit),
            ).fetchall()
        return [self._automation_run_from_row(row) for row in rows]

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

    def link_issue_artifact(
        self,
        *,
        project_id: str,
        issue_id: str | None,
        target_type: str,
        target_id: str,
        relation: str,
        source: str = "system",
        evidence_trace_ids: list[str] | None = None,
        evidence_span_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not issue_id:
            return None
        return self.create_issue_link(
            {
                "project_id": project_id,
                "issue_id": issue_id,
                "target_type": target_type,
                "target_id": target_id,
                "relation": relation,
                "source": source,
                "evidence_trace_ids": evidence_trace_ids or [],
                "evidence_span_ids": evidence_span_ids or [],
                "metadata": metadata or {},
            }
        )

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
        for candidate_trace_id in request.get("candidate_trace_ids") or []:
            if not isinstance(candidate_trace_id, str):
                continue
            if any(trace["trace_id"] == candidate_trace_id for trace in traces):
                continue
            candidate_trace = self.get_trace(project_id, candidate_trace_id)
            if candidate_trace is not None:
                traces.append(candidate_trace)
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
        evidence_trace_ids = [trace["trace_id"] for trace in traces]
        self.link_issue_artifact(
            project_id=project_id,
            issue_id=run["issue_id_nullable"],
            target_type="investigation_run",
            target_id=run["investigation_run_id"],
            relation="investigated_by",
            source="investigation_workflow",
            evidence_trace_ids=evidence_trace_ids,
        )
        self.link_issue_artifact(
            project_id=project_id,
            issue_id=run["issue_id_nullable"],
            target_type="impact_report",
            target_id=report["report_id"],
            relation="scoped_by",
            source="investigation_workflow",
            evidence_trace_ids=evidence_trace_ids,
            metadata={"matching_trace_count": report["matching_trace_count"]},
        )
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
        self._upsert_affected_entities_from_report(report)
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

    def list_affected_entities(
        self,
        project_id: str,
        issue_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if issue_id:
            clauses.append("issue_id = ?")
            params.append(issue_id)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM affected_entities
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC
                """,
                tuple(params),
            ).fetchall()
        return [self._affected_entity_from_row(row) for row in rows]

    def update_affected_entity(
        self,
        project_id: str,
        affected_entity_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        allowed_status = {"needs_review", "contacted", "fixed", "ignored", "false_positive"}
        status = request.get("status")
        if status is not None and status not in allowed_status:
            raise ValueError(f"Unsupported affected entity status: {status}")
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM affected_entities
                WHERE project_id = ? AND affected_entity_id = ?
                """,
                (project_id, affected_entity_id),
            ).fetchone()
            if row is None:
                raise KeyError(f"affected entity not found: {affected_entity_id}")
            conn.execute(
                """
                UPDATE affected_entities
                SET status = COALESCE(?, status),
                    owner_nullable = COALESCE(?, owner_nullable),
                    notes_nullable = COALESCE(?, notes_nullable),
                    updated_at = ?
                WHERE project_id = ? AND affected_entity_id = ?
                """,
                (
                    status,
                    request.get("owner_nullable"),
                    request.get("notes_nullable"),
                    now,
                    project_id,
                    affected_entity_id,
                ),
            )
            updated = conn.execute(
                """
                SELECT * FROM affected_entities
                WHERE project_id = ? AND affected_entity_id = ?
                """,
                (project_id, affected_entity_id),
            ).fetchone()
        if updated is None:
            raise KeyError(f"affected entity not found: {affected_entity_id}")
        return self._affected_entity_from_row(updated)

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
        if result.get("model_contradiction_adjudication"):
            check["model_contradiction_adjudication"] = result[
                "model_contradiction_adjudication"
            ]
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
            if result.get("model_contradiction_adjudication"):
                conn.execute(
                    """
                    INSERT INTO grounding_check_model_adjudications(
                      grounding_check_id, project_id, model_adjudication_json, created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        check["grounding_check_id"],
                        project_id,
                        encode_json(result["model_contradiction_adjudication"]),
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
            adjudication_rows = conn.execute(
                """
                SELECT grounding_check_id, model_adjudication_json
                FROM grounding_check_model_adjudications
                WHERE project_id = ?
                """,
                (project_id,),
            ).fetchall()
        extractions = {
            row["grounding_check_id"]: decode_json(row["model_extraction_json"], {})
            for row in extraction_rows
        }
        adjudications = {
            row["grounding_check_id"]: decode_json(row["model_adjudication_json"], {})
            for row in adjudication_rows
        }
        checks = [self._grounding_check_from_row(row) for row in rows]
        for check in checks:
            if check["grounding_check_id"] in extractions:
                check["model_extraction"] = extractions[check["grounding_check_id"]]
            if check["grounding_check_id"] in adjudications:
                check["model_contradiction_adjudication"] = adjudications[
                    check["grounding_check_id"]
                ]
        return checks

    def upsert_similarity_vector(self, record: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        vector = record["vector"]
        stored = {
            "vector_id": record.get("vector_id") or new_id("vector"),
            "project_id": record["project_id"],
            "entity_type": record["entity_type"],
            "entity_id": record["entity_id"],
            "trace_id_nullable": record.get("trace_id_nullable"),
            "representation_version": record["representation_version"],
            "provider": record["provider"],
            "model": record["model"],
            "dimensions": len(vector),
            "vector": vector,
            "source_hash": record["source_hash"],
            "source_summary": record.get("source_summary", {}),
            "created_at": now,
            "updated_at": now,
        }
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT vector_id, created_at
                FROM similarity_vectors
                WHERE project_id = ?
                  AND entity_type = ?
                  AND entity_id = ?
                  AND representation_version = ?
                """,
                (
                    stored["project_id"],
                    stored["entity_type"],
                    stored["entity_id"],
                    stored["representation_version"],
                ),
            ).fetchone()
            if existing is not None:
                stored["vector_id"] = existing["vector_id"]
                stored["created_at"] = existing["created_at"]
            conn.execute(
                """
                INSERT INTO similarity_vectors(
                  vector_id, project_id, entity_type, entity_id, trace_id_nullable,
                  representation_version, provider, model, dimensions, vector_json,
                  source_hash, source_summary_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, entity_type, entity_id, representation_version)
                DO UPDATE SET
                  trace_id_nullable = excluded.trace_id_nullable,
                  provider = excluded.provider,
                  model = excluded.model,
                  dimensions = excluded.dimensions,
                  vector_json = excluded.vector_json,
                  source_hash = excluded.source_hash,
                  source_summary_json = excluded.source_summary_json,
                  updated_at = excluded.updated_at
                """,
                (
                    stored["vector_id"],
                    stored["project_id"],
                    stored["entity_type"],
                    stored["entity_id"],
                    stored["trace_id_nullable"],
                    stored["representation_version"],
                    stored["provider"],
                    stored["model"],
                    stored["dimensions"],
                    encode_json(stored["vector"]),
                    stored["source_hash"],
                    encode_json(stored["source_summary"]),
                    stored["created_at"],
                    stored["updated_at"],
                ),
            )
        return stored

    def get_similarity_vector(
        self,
        project_id: str,
        entity_type: str,
        entity_id: str,
        representation_version: str,
    ) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM similarity_vectors
                WHERE project_id = ?
                  AND entity_type = ?
                  AND entity_id = ?
                  AND representation_version = ?
                """,
                (project_id, entity_type, entity_id, representation_version),
            ).fetchone()
        return self._similarity_vector_from_row(row) if row else None

    def list_similarity_vectors(
        self,
        project_id: str,
        representation_version: str,
        *,
        entity_type: str | None = None,
        trace_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["project_id = ?", "representation_version = ?"]
        params: list[Any] = [project_id, representation_version]
        if entity_type is not None:
            clauses.append("entity_type = ?")
            params.append(entity_type)
        if trace_ids is not None and not trace_ids:
            return []
        if trace_ids is not None:
            placeholders = ",".join("?" for _ in trace_ids)
            clauses.append(f"trace_id_nullable IN ({placeholders})")
            params.extend(trace_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM similarity_vectors
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC
                """,
                params,
            ).fetchall()
        return [self._similarity_vector_from_row(row) for row in rows]

    def similarity_index_summary(self, project_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT representation_version, entity_type, COUNT(*) AS count,
                       MAX(updated_at) AS last_updated_at
                FROM similarity_vectors
                WHERE project_id = ?
                GROUP BY representation_version, entity_type
                ORDER BY representation_version, entity_type
                """,
                (project_id,),
            ).fetchall()
        return {
            "project_id": project_id,
            "representations": [
                {
                    "representation_version": row["representation_version"],
                    "entity_type": row["entity_type"],
                    "count": row["count"],
                    "last_updated_at": row["last_updated_at"],
                }
                for row in rows
            ],
        }

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
        audit_summary = self._audit_summary(project_id)
        sections: dict[str, Any] = {
            "metadata": {"project_id": project_id},
            "traces": traces,
            "trace_jsonl": _jsonl(traces),
            "spans": spans,
            "span_jsonl": _jsonl(spans),
            "payloads": payloads if include_payloads else _payload_metadata_only(payloads),
            "scores": self.list_scores(project_id),
            "behavior_matches": self.list_behavior_matches(project_id),
            "judges": self.list_judges(project_id),
            "eval_runs": self.list_eval_runs(project_id),
            "eval_results": self._list_eval_results(project_id),
            "behaviors": self.list_behaviors(project_id),
            "datasets": self.list_datasets(project_id),
            "dataset_examples": self._list_dataset_examples(project_id),
            "prompts": self.list_prompts(project_id),
            "issues": self.list_issues(project_id),
            "issue_links": self._list_issue_links(project_id),
            "investigations": self.list_investigation_runs(project_id),
            "impact_reports": self.list_impact_reports(project_id),
            "affected_entities": self._list_affected_entities(project_id),
            "context_packs": self.list_agent_context_packs(project_id),
            "review_tasks": self.list_review_tasks(project_id),
            "grounding_checks": self.list_grounding_checks(project_id),
            "novelty_runs": self.list_novelty_runs(project_id),
            "mcp_tool_observations": self.list_mcp_tool_observations(project_id, limit=10000),
            "secret_refs": self.list_secret_refs(project_id),
            "audit_summary": audit_summary,
        }
        manifest = {
            "export_id": new_id("export"),
            "project_id": project_id,
            "created_at": utc_now(),
            "include_payloads": include_payloads,
            "included_classifications": _included_classifications(sections),
            "sections": {
                name: {
                    "count": _section_count(value),
                    "sha256": hashlib.sha256(encode_json(value).encode()).hexdigest(),
                }
                for name, value in sections.items()
            },
        }
        return {"manifest": manifest, **sections}

    def tombstone_trace(self, project_id: str, trace_id: str) -> dict[str, Any]:
        trace = self.get_trace(project_id, trace_id)
        if trace is None:
            raise KeyError(f"trace not found: {trace_id}")
        now = utc_now()
        effects: dict[str, int] = {}
        with self.connect() as conn:
            span_ids = [
                row["span_id"]
                for row in conn.execute(
                    """
                    SELECT span_id FROM trace_spans
                    WHERE project_id = ? AND trace_id = ?
                    """,
                    (project_id, trace_id),
                ).fetchall()
            ]
            removal_ids = {trace_id, *span_ids}
            dataset_example_ids = [
                row["dataset_example_id"]
                for row in conn.execute(
                    """
                    SELECT dataset_example_id FROM dataset_examples
                    WHERE project_id = ? AND source_trace_id = ?
                    """,
                    (project_id, trace_id),
                ).fetchall()
            ]
            if dataset_example_ids:
                placeholders = ",".join("?" for _ in dataset_example_ids)
                cursor = conn.execute(
                    f"""
                    DELETE FROM eval_results
                    WHERE project_id = ? AND dataset_example_id IN ({placeholders})
                    """,
                    (project_id, *dataset_example_ids),
                )
                effects["eval_results"] = cursor.rowcount
            else:
                effects["eval_results"] = 0
            for table, column in [
                ("trace_dimensions", "trace_id"),
                ("code_contexts", "trace_id"),
                ("grounding_checks", "trace_id"),
                ("dataset_examples", "source_trace_id"),
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
                UPDATE issues
                SET seed_trace_id_nullable = NULL, updated_at = ?
                WHERE project_id = ? AND seed_trace_id_nullable = ?
                """,
                (now, project_id, trace_id),
            )
            effects["issues_seed_trace_scrubbed"] = cursor.rowcount
            cursor = conn.execute(
                """
                UPDATE investigation_runs
                SET seed_trace_id_nullable = NULL, updated_at = ?
                WHERE project_id = ? AND seed_trace_id_nullable = ?
                """,
                (now, project_id, trace_id),
            )
            effects["investigation_seed_trace_scrubbed"] = cursor.rowcount
            effects["investigation_results_scrubbed"] = self._scrub_json_column_references(
                conn,
                project_id,
                table="investigation_runs",
                id_column="investigation_run_id",
                json_column="result_json",
                removals=removal_ids,
                updated_at=now,
            )
            effects["review_task_evidence_scrubbed"] = self._scrub_json_column_references(
                conn,
                project_id,
                table="review_tasks",
                id_column="review_task_id",
                json_column="evidence_ids_json",
                removals=removal_ids,
                updated_at=now,
            )
            issue_link_target_ids = [trace_id, *span_ids, *dataset_example_ids]
            if issue_link_target_ids:
                placeholders = ",".join("?" for _ in issue_link_target_ids)
                cursor = conn.execute(
                    f"""
                    DELETE FROM issue_links
                    WHERE project_id = ? AND target_id IN ({placeholders})
                    """,
                    (project_id, *issue_link_target_ids),
                )
                effects["issue_link_targets_removed"] = cursor.rowcount
            else:
                effects["issue_link_targets_removed"] = 0
            effects["issue_link_trace_evidence_scrubbed"] = self._scrub_json_column_references(
                conn,
                project_id,
                table="issue_links",
                id_column="issue_link_id",
                json_column="evidence_trace_ids_json",
                removals={trace_id},
                updated_at=now,
            )
            effects["issue_link_span_evidence_scrubbed"] = self._scrub_json_column_references(
                conn,
                project_id,
                table="issue_links",
                id_column="issue_link_id",
                json_column="evidence_span_ids_json",
                removals=set(span_ids),
                updated_at=now,
            )
            effects["context_packs_scrubbed"] = self._scrub_context_packs(
                conn,
                project_id,
                trace_id,
                removals=removal_ids,
                updated_at=now,
            )
            effects["impact_reports_scrubbed"] = self._scrub_impact_reports(
                conn,
                project_id,
                trace_id,
                updated_at=now,
            )
            effects["affected_entities_scrubbed"] = self._scrub_affected_entities(
                conn,
                project_id,
                trace_id,
                updated_at=now,
            )
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
            cursor = conn.execute(
                """
                DELETE FROM similarity_vectors
                WHERE project_id = ?
                  AND (trace_id_nullable = ? OR (entity_type = 'trace' AND entity_id = ?))
                """,
                (project_id, trace_id, trace_id),
            )
            effects["similarity_vectors"] = cursor.rowcount
            effects["prompt_links"] = 0
            effects["derived_views"] = (
                effects["impact_reports_scrubbed"]
                + effects["affected_entities_scrubbed"]
                + effects["context_packs_scrubbed"]
            )
        return {
            "status": "tombstoned",
            "project_id": project_id,
            "trace_id": trace_id,
            "deleted_at": now,
            "effects": effects,
        }

    @staticmethod
    def _scrub_json_column_references(
        conn: sqlite3.Connection,
        project_id: str,
        *,
        table: str,
        id_column: str,
        json_column: str,
        removals: set[str],
        updated_at: str,
    ) -> int:
        changed_count = 0
        rows = conn.execute(
            f"SELECT {id_column}, {json_column} FROM {table} WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        for row in rows:
            value = decode_json(row[json_column], [])
            scrubbed, changed = _scrub_json_references(value, removals)
            if not changed:
                continue
            assignments = f"{json_column} = ?"
            params: tuple[Any, ...]
            if table in {"review_tasks", "investigation_runs"}:
                assignments = f"{assignments}, updated_at = ?"
                params = (encode_json(scrubbed), updated_at, project_id, row[id_column])
            else:
                params = (encode_json(scrubbed), project_id, row[id_column])
            conn.execute(
                f"""
                UPDATE {table}
                SET {assignments}
                WHERE project_id = ? AND {id_column} = ?
                """,
                params,
            )
            changed_count += 1
        return changed_count

    @staticmethod
    def _scrub_context_packs(
        conn: sqlite3.Connection,
        project_id: str,
        trace_id: str,
        *,
        removals: set[str],
        updated_at: str,
    ) -> int:
        del updated_at
        changed_count = 0
        rows = conn.execute(
            """
            SELECT context_pack_id, source_trace_ids_json, content_json
            FROM agent_context_packs
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchall()
        for row in rows:
            source_ids = decode_json(row["source_trace_ids_json"], [])
            next_source_ids, source_changed = _remove_values(source_ids, {trace_id})
            content = decode_json(row["content_json"], {})
            scrubbed_content, content_changed = _scrub_json_references(content, removals)
            if not source_changed and not content_changed:
                continue
            if not next_source_ids:
                scrubbed_content = {
                    "status": "redacted_due_to_trace_delete",
                    "redacted_trace_count": 1,
                }
            conn.execute(
                """
                UPDATE agent_context_packs
                SET source_trace_ids_json = ?, content_json = ?
                WHERE project_id = ? AND context_pack_id = ?
                """,
                (
                    encode_json(next_source_ids),
                    encode_json(scrubbed_content),
                    project_id,
                    row["context_pack_id"],
                ),
            )
            changed_count += 1
        return changed_count

    @staticmethod
    def _scrub_impact_reports(
        conn: sqlite3.Connection,
        project_id: str,
        trace_id: str,
        *,
        updated_at: str,
    ) -> int:
        del updated_at
        changed_count = 0
        rows = conn.execute(
            """
            SELECT report_id, representative_trace_ids_json, affected_entities_json
            FROM impact_reports
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchall()
        for row in rows:
            reps = decode_json(row["representative_trace_ids_json"], [])
            next_reps, reps_changed = _remove_values(reps, {trace_id})
            entities = decode_json(row["affected_entities_json"], [])
            next_entities = []
            entities_changed = False
            for entity in entities:
                trace_ids = entity.get("trace_ids", []) if isinstance(entity, dict) else []
                next_trace_ids, changed = _remove_values(trace_ids, {trace_id})
                entities_changed = entities_changed or changed
                if isinstance(entity, dict):
                    next_entities.append({**entity, "trace_ids": next_trace_ids})
                else:
                    next_entities.append(entity)
            if not reps_changed and not entities_changed:
                continue
            conn.execute(
                """
                UPDATE impact_reports
                SET representative_trace_ids_json = ?,
                    affected_entities_json = ?,
                    affected_entity_count = ?
                WHERE project_id = ? AND report_id = ?
                """,
                (
                    encode_json(next_reps),
                    encode_json(next_entities),
                    sum(
                        1
                        for entity in next_entities
                        if isinstance(entity, dict) and entity.get("trace_ids")
                    ),
                    project_id,
                    row["report_id"],
                ),
            )
            changed_count += 1
        return changed_count

    @staticmethod
    def _scrub_affected_entities(
        conn: sqlite3.Connection,
        project_id: str,
        trace_id: str,
        *,
        updated_at: str,
    ) -> int:
        changed_count = 0
        rows = conn.execute(
            """
            SELECT affected_entity_id, trace_ids_json
            FROM affected_entities
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchall()
        for row in rows:
            trace_ids = decode_json(row["trace_ids_json"], [])
            next_trace_ids, changed = _remove_values(trace_ids, {trace_id})
            if not changed:
                continue
            status = "deleted" if not next_trace_ids else "needs_review"
            conn.execute(
                """
                UPDATE affected_entities
                SET trace_ids_json = ?, status = ?, updated_at = ?
                WHERE project_id = ? AND affected_entity_id = ?
                """,
                (
                    encode_json(next_trace_ids),
                    status,
                    updated_at,
                    project_id,
                    row["affected_entity_id"],
                ),
            )
            changed_count += 1
        return changed_count

    def _upsert_affected_entities_from_report(self, report: dict[str, Any]) -> None:
        issue_id = report.get("issue_id")
        if not issue_id:
            return
        now = utc_now()
        link_requests = []
        with self.connect() as conn:
            for entity in report.get("affected_entities", []):
                if not isinstance(entity, dict):
                    continue
                entity_type = entity.get("entity_type")
                entity_id = entity.get("entity_id")
                if not isinstance(entity_type, str) or not isinstance(entity_id, str):
                    continue
                trace_ids = [str(value) for value in entity.get("trace_ids", [])]
                existing = conn.execute(
                    """
                    SELECT * FROM affected_entities
                    WHERE project_id = ? AND issue_id = ? AND entity_type = ? AND entity_id = ?
                    """,
                    (report["project_id"], issue_id, entity_type, entity_id),
                ).fetchone()
                if existing is None:
                    affected_entity_id = new_id("affected_entity")
                    conn.execute(
                        """
                        INSERT INTO affected_entities(
                          affected_entity_id, project_id, issue_id, entity_type,
                          entity_id, display_name_nullable, trace_ids_json, status,
                          owner_nullable, notes_nullable, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            affected_entity_id,
                            report["project_id"],
                            issue_id,
                            entity_type,
                            entity_id,
                            entity.get("display_name_nullable"),
                            encode_json(trace_ids),
                            entity.get("status") or "needs_review",
                            entity.get("owner_nullable"),
                            entity.get("notes_nullable"),
                            now,
                            now,
                        ),
                    )
                    link_requests.append(
                        {
                            "project_id": report["project_id"],
                            "issue_id": issue_id,
                            "target_type": "affected_entity",
                            "target_id": affected_entity_id,
                            "relation": "affected_entity",
                            "source": "impact_report",
                            "evidence_trace_ids": trace_ids,
                        }
                    )
                    continue
                merged_trace_ids = sorted(
                    set(decode_json(existing["trace_ids_json"], []) + trace_ids)
                )
                conn.execute(
                    """
                    UPDATE affected_entities
                    SET trace_ids_json = ?, updated_at = ?
                    WHERE project_id = ? AND affected_entity_id = ?
                    """,
                    (
                        encode_json(merged_trace_ids),
                        now,
                        report["project_id"],
                        existing["affected_entity_id"],
                    ),
                )
        for request in link_requests:
            self.link_issue_artifact(**request)

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

    def _list_dataset_examples(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM dataset_examples
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._dataset_example_from_row(row) for row in rows]

    def _list_eval_results(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM eval_results
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._eval_result_from_row(row) for row in rows]

    def _list_affected_entities(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM affected_entities
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._affected_entity_from_row(row) for row in rows]

    def _list_issue_links(self, project_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM issue_links
                WHERE project_id = ?
                ORDER BY created_at DESC
                """,
                (project_id,),
            ).fetchall()
        return [self._issue_link_from_row(row) for row in rows]

    def _audit_summary(self, project_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT action, target_type, COUNT(*) AS count, MAX(created_at) AS latest_at
                FROM audit_log
                WHERE project_id = ? OR project_id IS NULL
                GROUP BY action, target_type
                ORDER BY count DESC, action ASC
                """,
                (project_id,),
            ).fetchall()
        return {
            "project_id": project_id,
            "groups": [dict(row) for row in rows],
            "total_count": sum(int(row["count"]) for row in rows),
        }

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
        runtime_distribution = _runtime_provenance_distribution(traces)
        if runtime_distribution:
            suspected.append(
                {
                    "candidate_id": new_id("root_cause_candidate"),
                    "hypothesis": "Trace cohort has correlated runtime provenance identifiers.",
                    "evidence_summary": {
                        "runtime_provenance_distribution": runtime_distribution
                    },
                    "representative_trace_ids": trace_ids[:5],
                    "correlated_fields": sorted(runtime_distribution),
                    "confidence_or_uncertainty": "deterministic_correlation_only",
                }
            )
        suspected.extend(
            self._differential_root_cause_candidates(
                project_id,
                failing_traces=traces,
                failing_trace_ids=set(trace_ids),
                dimensions_by_trace=dimensions_by_trace,
            )
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
            "deployment_distribution": runtime_distribution,
            "suspected_root_causes": suspected,
            "representative_trace_ids": trace_ids[:10],
            "generated_summary": (
                f"Deterministic investigation found {len(traces)} matching traces "
                f"across {len(sessions)} sessions."
            ),
            "created_at": now,
        }

    def _differential_root_cause_candidates(
        self,
        project_id: str,
        *,
        failing_traces: list[dict[str, Any]],
        failing_trace_ids: set[str],
        dimensions_by_trace: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        if not failing_traces:
            return []
        baseline_traces = [
            trace
            for trace in self.search_traces(project_id, filters={}, limit=500)
            if trace["trace_id"] not in failing_trace_ids
        ]
        failing_index = self._cohort_feature_index(
            project_id,
            failing_traces,
            dimensions_by_trace,
        )
        baseline_index = self._cohort_feature_index(
            project_id,
            baseline_traces,
            dimensions_by_trace,
        )
        candidates = []
        failing_size = len(failing_traces)
        baseline_size = len(baseline_traces)
        for feature, failing_refs in failing_index.items():
            baseline_refs = baseline_index.get(feature, {"trace_ids": set(), "span_ids": set()})
            failing_count = len(failing_refs["trace_ids"])
            baseline_count = len(baseline_refs["trace_ids"])
            failing_rate = failing_count / failing_size
            baseline_rate = baseline_count / baseline_size if baseline_size else 0.0
            rate_delta = failing_rate - baseline_rate
            if rate_delta <= 0:
                continue
            field, value = feature
            candidates.append(
                {
                    "candidate_id": new_id("root_cause_candidate"),
                    "hypothesis": _differential_hypothesis(field, value),
                    "evidence_summary": {
                        "field": field,
                        "value": value,
                        "failing_count": failing_count,
                        "baseline_count": baseline_count,
                        "failing_cohort_size": failing_size,
                        "baseline_cohort_size": baseline_size,
                    },
                    "failing_cohort_metric": {
                        "count": failing_count,
                        "rate": round(failing_rate, 4),
                    },
                    "baseline_cohort_metric": {
                        "count": baseline_count,
                        "rate": round(baseline_rate, 4),
                    },
                    "lift_or_delta": {
                        "rate_delta": round(rate_delta, 4),
                        "lift": None
                        if baseline_rate == 0
                        else round(failing_rate / baseline_rate, 4),
                    },
                    "representative_trace_ids": sorted(failing_refs["trace_ids"])[:5],
                    "representative_span_ids": sorted(failing_refs["span_ids"])[:5],
                    "confidence_or_uncertainty": (
                        "deterministic_differential_signal_only_not_causal"
                    ),
                }
            )
        return sorted(
            candidates,
            key=lambda item: (
                item["lift_or_delta"]["rate_delta"],
                item["failing_cohort_metric"]["count"],
            ),
            reverse=True,
        )[:20]

    def _cohort_feature_index(
        self,
        project_id: str,
        traces: list[dict[str, Any]],
        dimensions_by_trace: dict[str, list[dict[str, Any]]],
    ) -> dict[tuple[str, str], dict[str, set[str]]]:
        index: dict[tuple[str, str], dict[str, set[str]]] = {}

        def add(field: str, value: Any, trace_id: str, span_id: str | None = None) -> None:
            text = _optional_string(value)
            if not text:
                return
            refs = index.setdefault((field, text), {"trace_ids": set(), "span_ids": set()})
            refs["trace_ids"].add(trace_id)
            if span_id:
                refs["span_ids"].add(span_id)

        for trace in traces:
            trace_id = trace["trace_id"]
            add("status", trace.get("status"), trace_id)
            provenance = _trace_runtime_provenance(trace)
            for key in ["prompt_version_id", "agent_config_version_id", "deployment_context_id"]:
                add(key, provenance.get(key), trace_id)
            for tool_version_id in provenance["tool_version_ids"]:
                add("tool_version_id", tool_version_id, trace_id)
            for dimension in dimensions_by_trace.get(trace_id, []):
                add(f"dimension:{dimension['key']}", dimension.get("value"), trace_id)
            for span in self.list_spans(project_id, trace_id):
                attributes = (
                    span.get("attributes") if isinstance(span.get("attributes"), dict) else {}
                )
                add("span_status", span.get("status"), trace_id, span["span_id"])
                add(
                    "error_type",
                    attributes.get("error.type") or attributes.get("error_type"),
                    trace_id,
                    span["span_id"],
                )
                if span.get("span_type") == "tool":
                    tool_name = attributes.get("tool.name")
                    nested_tool = attributes.get("tool")
                    if not tool_name and isinstance(nested_tool, dict):
                        tool_name = nested_tool.get("name")
                    add("tool_name", tool_name or span.get("name"), trace_id, span["span_id"])
        return index

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
                    trace["prompt_version_id"] or "",
                    trace["agent_config_version_id"] or "",
                    trace["deployment_context_id"] or "",
                    trace["tool_version_ids_json"] or "",
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
    def _secret_ref_from_row(
        row: sqlite3.Row,
        *,
        include_ciphertext: bool,
    ) -> dict[str, Any]:
        item = {
            "secret_ref": row["secret_ref"],
            "org_id": row["org_id"],
            "project_id": row["project_id"],
            "purpose": row["purpose"],
            "provider": row["provider"],
            "status": row["status"],
            "current_version": row["current_version"],
            "encryption_mode": row["encryption_mode"],
            "ciphertext_sha256": row["ciphertext_sha256"],
            "rotation_due_at": row["rotation_due_at"],
            "rotated_at": row["rotated_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
            "has_value": True,
            "redacted_value": "secret://redacted",
        }
        if include_ciphertext:
            item["ciphertext"] = row["ciphertext"]
        return item

    @staticmethod
    def _secret_access_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "secret_access_id": row["secret_access_id"],
            "project_id": row["project_id"],
            "secret_ref": row["secret_ref"],
            "actor_id": row["actor_id"],
            "action": row["action"],
            "purpose": row["purpose"],
            "created_at": row["created_at"],
        }

    @staticmethod
    def _worker_heartbeat_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "worker_id": row["worker_id"],
            "project_id": row["project_id"],
            "worker_type": row["worker_type"],
            "status": row["status"],
            "queue_depth": row["queue_depth"],
            "details": decode_json(row["details_json"], {}),
            "last_seen_at": row["last_seen_at"],
        }

    @staticmethod
    def _api_key_from_row(row: sqlite3.Row, *, include_hash: bool) -> dict[str, Any]:
        item = {
            "api_key_id": row["api_key_id"],
            "project_id": row["project_id"],
            "name": row["name"] or row["api_key_id"],
            "actor_id": row["actor_id"],
            "actor_type": row["actor_type"] or "service_account",
            "role": row["role"] or "viewer",
            "scopes": decode_json(row["scopes_json"], []),
            "status": row["status"] or ("revoked" if row["revoked_at"] else "active"),
            "last_used_at": row["last_used_at"],
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "revoked_by": row["revoked_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"] or row["created_at"],
        }
        if include_hash:
            item["key_hash"] = row["key_hash"]
        return item

    @staticmethod
    def _service_account_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "service_account_id": row["service_account_id"],
            "org_id": row["org_id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "role": row["role"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _auth_user_from_row(row: sqlite3.Row) -> dict[str, Any]:
        item = {
            "user_id": row["user_id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "auth_provider": row["auth_provider"],
            "external_subject": row["external_subject"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if "membership_id" in row.keys():
            item["membership"] = {
                "membership_id": row["membership_id"],
                "role": row["role"],
                "status": row["membership_status"],
            }
        return item

    @staticmethod
    def _membership_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "membership_id": row["membership_id"],
            "org_id": row["org_id"],
            "project_id": row["project_id"],
            "user_id": row["user_id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "role": row["role"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _invite_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "invite_id": row["invite_id"],
            "org_id": row["org_id"],
            "project_id": row["project_id"],
            "email": row["email"],
            "role": row["role"],
            "status": row["status"],
            "invited_by": row["invited_by"],
            "expires_at": row["expires_at"],
            "accepted_at": row["accepted_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _invite_delivery_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "invite_delivery_id": row["invite_delivery_id"],
            "invite_id": row["invite_id"],
            "project_id": row["project_id"],
            "delivery_channel": row["delivery_channel"],
            "delivery_status": row["delivery_status"],
            "recipient_email": row["recipient_email"],
            "payload": decode_json(row["payload_json"], {}),
            "error_nullable": row["error_nullable"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _auth_session_from_row(
        row: sqlite3.Row,
        *,
        include_hashes: bool,
    ) -> dict[str, Any]:
        item = {
            "auth_session_id": row["auth_session_id"],
            "user_id": row["user_id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "org_id": row["org_id"],
            "project_id": row["project_id"],
            "cookie_policy": decode_json(row["cookie_policy_json"], {}),
            "ip_hint": row["ip_hint"],
            "user_agent_hint": row["user_agent_hint"],
            "status": row["status"],
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_hashes:
            item["session_token_hash"] = row["session_token_hash"]
            item["csrf_token_hash"] = row["csrf_token_hash"]
        return item

    @staticmethod
    def _auth_decision_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "record_id": row["record_id"],
            "topic": row["topic"],
            "decision": row["decision"],
            "rationale": row["rationale"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

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
            "prompt_version_id": row["prompt_version_id"],
            "agent_config_version_id": row["agent_config_version_id"],
            "deployment_context_id": row["deployment_context_id"],
            "tool_version_ids": decode_json(row["tool_version_ids_json"], []),
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
            "resource": decode_json(row["resource_json"], {}),
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
            "failure_reason": row["failure_reason"],
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
    def _behavior_match_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "behavior_match_id": row["behavior_match_id"],
            "project_id": row["project_id"],
            "behavior_id": row["behavior_id"],
            "trace_id": row["trace_id"],
            "span_id": row["span_id"],
            "score_id": row["score_id"],
            "status": row["status"],
            "evidence_span_ids": decode_json(row["evidence_span_ids_json"], []),
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
    def _issue_link_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "issue_link_id": row["issue_link_id"],
            "project_id": row["project_id"],
            "issue_id": row["issue_id"],
            "target_type": row["target_type"],
            "target_id": row["target_id"],
            "relation": row["relation"],
            "source": row["source"],
            "evidence_trace_ids": decode_json(row["evidence_trace_ids_json"], []),
            "evidence_span_ids": decode_json(row["evidence_span_ids_json"], []),
            "metadata": decode_json(row["metadata_json"], {}),
            "created_at": row["created_at"],
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
            "agent_config_version_id": row["agent_config_version_id"],
            "runtime_context": decode_json(row["runtime_context_json"], {}),
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
    def _affected_entity_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "affected_entity_id": row["affected_entity_id"],
            "project_id": row["project_id"],
            "issue_id": row["issue_id"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "display_name_nullable": row["display_name_nullable"],
            "trace_ids": decode_json(row["trace_ids_json"], []),
            "status": row["status"],
            "owner_nullable": row["owner_nullable"],
            "notes_nullable": row["notes_nullable"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
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
    def _similarity_vector_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "vector_id": row["vector_id"],
            "project_id": row["project_id"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "trace_id_nullable": row["trace_id_nullable"],
            "representation_version": row["representation_version"],
            "provider": row["provider"],
            "model": row["model"],
            "dimensions": row["dimensions"],
            "vector": decode_json(row["vector_json"], []),
            "source_hash": row["source_hash"],
            "source_summary": decode_json(row["source_summary_json"], {}),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
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
