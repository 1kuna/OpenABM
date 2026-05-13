from __future__ import annotations

from typing import Any

CLASSIFICATION_LEVELS = ("public", "internal", "confidential", "restricted", "secret")
CLASSIFICATION_RANK = {level: index for index, level in enumerate(CLASSIFICATION_LEVELS)}


def normalize_classification(value: str | None, default: str = "internal") -> str:
    candidate = (value or default).lower()
    if candidate not in CLASSIFICATION_RANK:
        raise ValueError(f"Unknown data classification: {value}")
    return candidate


def can_access(classification: str, max_classification: str) -> bool:
    classification = normalize_classification(classification)
    max_classification = normalize_classification(max_classification)
    return CLASSIFICATION_RANK[classification] <= CLASSIFICATION_RANK[max_classification]


def classify_payload(payload: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    classification = normalize_classification(policy.get("default_classification"), "internal")
    matched_rules: list[dict[str, Any]] = []

    for rule in policy.get("rules", []):
        path = rule.get("path") or rule.get("field")
        if not path:
            continue
        value = _lookup_path(payload, str(path))
        if value is None:
            continue
        if "contains" in rule and str(rule["contains"]) not in str(value):
            continue
        rule_classification = normalize_classification(rule.get("classification"), classification)
        if CLASSIFICATION_RANK[rule_classification] > CLASSIFICATION_RANK[classification]:
            classification = rule_classification
        matched_rules.append(
            {
                "rule_id": rule.get("rule_id"),
                "path": path,
                "classification": rule_classification,
            }
        )

    return {"classification": classification, "matched_rules": matched_rules}


def redact_if_needed(
    payload: dict[str, Any],
    classification: str,
    max_classification: str,
) -> dict[str, Any]:
    if can_access(classification, max_classification):
        return payload
    return {
        "redacted": True,
        "classification": normalize_classification(classification),
        "reason": "payload classification exceeds caller allowance",
    }


def _lookup_path(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current
