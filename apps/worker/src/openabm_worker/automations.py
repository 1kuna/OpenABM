from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from openabm_worker.conditions import evaluate_condition_group


def evaluate_automation_conditions(
    automation: dict[str, Any],
    trace: dict[str, Any] | None,
    spans: list[dict[str, Any]],
) -> dict[str, Any]:
    conditions = automation.get("conditions") or {"combine": "all", "items": []}
    context = {
        "trace": trace or {},
        "spans": spans,
        "span_count": len(spans),
        "attributes": (trace or {}).get("attributes", {}),
    }
    return evaluate_condition_group(conditions, context)


def planned_automation_actions(
    automation: dict[str, Any],
    *,
    trace_id: str | None,
) -> list[dict[str, Any]]:
    planned = []
    for index, action in enumerate(automation.get("actions", [])):
        action_type = action.get("type")
        planned.append(
            {
                "index": index,
                "type": action_type,
                "status": "planned",
                "idempotency_key": _action_idempotency_key(
                    automation["automation_id"],
                    index,
                    trace_id,
                ),
                "action": action,
            }
        )
    return planned


def plan_automation_cooldown(
    automation: dict[str, Any],
    *,
    project_id: str,
    trace_id: str | None,
) -> dict[str, Any]:
    cooldown = automation.get("cooldown") or {}
    seconds = _positive_int(cooldown.get("seconds"))
    if seconds <= 0:
        return {"configured": False, "active": False}
    return {
        "configured": True,
        "active": False,
        "seconds": seconds,
        "cooldown_key": _cooldown_key(
            cooldown.get("key"),
            automation_id=automation["automation_id"],
            project_id=project_id,
            trace_id=trace_id,
        ),
    }


def evaluate_automation_cooldown(
    cooldown_plan: dict[str, Any],
    latest_run: dict[str, Any] | None,
    *,
    now: str,
) -> dict[str, Any]:
    if not cooldown_plan.get("configured"):
        return cooldown_plan
    result = {**cooldown_plan, "active": False}
    if latest_run is None:
        return result
    latest_at = latest_run.get("completed_at") or latest_run.get("started_at")
    elapsed_seconds = _elapsed_seconds(latest_at, now)
    result["last_run_id"] = latest_run.get("automation_run_id")
    result["elapsed_seconds"] = elapsed_seconds
    if elapsed_seconds is None:
        result["reason"] = "last run timestamp unavailable"
        return result
    remaining = int(result["seconds"]) - elapsed_seconds
    if remaining > 0:
        result["active"] = True
        result["remaining_seconds"] = remaining
    return result


def _action_idempotency_key(
    automation_id: str,
    index: int,
    trace_id: str | None,
) -> str:
    return f"{automation_id}:{index}:{trace_id or 'none'}"


def _cooldown_key(
    template: Any,
    *,
    automation_id: str,
    project_id: str,
    trace_id: str | None,
) -> str:
    if template in (None, "", "automation_id + project_id", "project"):
        return f"{automation_id}:{project_id}"
    if template in {"automation_id + project_id + trace_id", "trace"}:
        return f"{automation_id}:{project_id}:{trace_id or 'none'}"
    return str(template).format(
        automation_id=automation_id,
        project_id=project_id,
        trace_id=trace_id or "none",
    )


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _elapsed_seconds(start: Any, end: Any) -> int | None:
    start_dt = _parse_utc_datetime(start)
    end_dt = _parse_utc_datetime(end)
    if start_dt is None or end_dt is None:
        return None
    return max(0, int((end_dt - start_dt).total_seconds()))


def _parse_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
