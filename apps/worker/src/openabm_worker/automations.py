from __future__ import annotations

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


def _action_idempotency_key(
    automation_id: str,
    index: int,
    trace_id: str | None,
) -> str:
    return f"{automation_id}:{index}:{trace_id or 'none'}"
