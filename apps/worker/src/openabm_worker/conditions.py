from __future__ import annotations

import operator
import re
from typing import Any


def evaluate_condition_group(group: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    combine = group.get("combine", "all")
    items = group.get("items", [])
    results = [_evaluate_item(item, context) for item in items]
    if combine == "all":
        passed = all(result["passed"] for result in results)
    elif combine == "any":
        passed = any(result["passed"] for result in results)
    else:
        passed = False
    return {"passed": passed, "combine": combine, "items": results}


def _evaluate_item(item: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    if "items" in item:
        nested = evaluate_condition_group(item, context)
        return {"passed": nested["passed"], "nested": nested}

    field = item["field"]
    op = item["op"]
    expected = item.get("value")
    actual = _resolve_path(context, field)
    passed = _compare(actual, op, expected)
    return {"field": field, "op": op, "expected": expected, "actual": actual, "passed": passed}


def _resolve_path(context: dict[str, Any], path: str) -> Any:
    value: Any = context
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def _compare(actual: Any, op: str, expected: Any) -> bool:
    operations = {
        "eq": operator.eq,
        "neq": operator.ne,
        "gt": operator.gt,
        "gte": operator.ge,
        "lt": operator.lt,
        "lte": operator.le,
    }
    if op in operations:
        if actual is None:
            return False
        return bool(operations[op](actual, expected))
    if op == "exists":
        return actual is not None
    if op == "not_exists":
        return actual is None
    if op == "contains":
        return actual is not None and expected in actual
    if op == "not_contains":
        return actual is None or expected not in actual
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    if op == "matches_regex":
        return actual is not None and re.search(str(expected), str(actual)) is not None
    return False

