from __future__ import annotations

from typing import Any

from openabm_api.ids import new_id
from openabm_api.time import utc_now

from openabm_worker.conditions import evaluate_condition_group
from openabm_worker.context_packets import build_trace_context_packet

RUBRIC_JUDGE_OUTPUT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "score", "confidence", "reasoning", "evidence_span_ids"],
    "properties": {
        "verdict": {"enum": ["pass", "fail", "unsure"]},
        "score": {"type": "number", "minimum": 0, "maximum": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string"},
        "evidence_span_ids": {"type": "array", "items": {"type": "string"}},
        "failure_mode": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"]},
    },
}


def validate_judge_output(
    output: dict[str, Any],
    *,
    trace_id: str,
    judge_id: str,
    judge_version_id: str | None,
    preserved_span_ids: set[str],
    require_span_citations: bool,
) -> dict[str, Any]:
    evidence = list(output.get("evidence_span_ids") or [])
    if require_span_citations and not evidence:
        return _invalid(trace_id, judge_id, judge_version_id, "missing_citations")
    if any(span_id not in preserved_span_ids for span_id in evidence):
        return _invalid(trace_id, judge_id, judge_version_id, "invalid_citation")

    verdict = output.get("verdict")
    if verdict not in {"pass", "fail", "unsure"}:
        return _invalid(trace_id, judge_id, judge_version_id, "invalid_verdict")

    return {
        "score_id": new_id("score"),
        "trace_id": trace_id,
        "span_id": None,
        "judge_id": judge_id,
        "judge_version_id": judge_version_id,
        "status": "succeeded",
        "failure_reason": None,
        "value": {"verdict": verdict, "score": output.get("score")},
        "confidence": output.get("confidence"),
        "reasoning": output.get("reasoning"),
        "evidence_span_ids": evidence,
        "failure_mode": output.get("failure_mode"),
        "cost": None,
        "latency_ms": None,
        "created_at": utc_now(),
    }


def run_deterministic_rule_judge(
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
    judge: dict[str, Any],
) -> dict[str, Any]:
    rule = judge["rule"]
    span_matches = []
    for span in spans:
        context = {"trace": trace, "span": span, "attributes": span.get("attributes", {})}
        result = evaluate_condition_group(rule["conditions"], context)
        if result["passed"]:
            span_matches.append(span["span_id"])

    if rule.get("match_semantics") == "any_match_is_pass":
        passed = bool(span_matches)
    else:
        passed = not span_matches
    verdict = "pass" if passed else "fail"
    return {
        "score_id": new_id("score"),
        "trace_id": trace["trace_id"],
        "span_id": None,
        "judge_id": judge["judge_id"],
        "judge_version_id": judge.get("judge_version_id"),
        "status": "succeeded",
        "failure_reason": None,
        "value": {"verdict": verdict, "score": 1.0 if passed else 0.0},
        "confidence": 1.0,
        "reasoning": "Deterministic rule evaluation completed.",
        "evidence_span_ids": span_matches,
        "failure_mode": None if passed else rule.get("failure_mode"),
        "cost": None,
        "latency_ms": 0,
        "created_at": utc_now(),
    }


async def run_rubric_judge(
    provider: Any,
    trace: dict[str, Any],
    spans: list[dict[str, Any]],
    judge: dict[str, Any],
    *,
    token_budget: int,
) -> dict[str, Any]:
    context_packet = build_trace_context_packet(trace, spans, token_budget=token_budget)
    completion = await provider.structured_completion(
        {
            "messages": [
                {
                    "role": "system",
                    "content": _rubric_system_prompt(judge),
                },
                {
                    "role": "user",
                    "content": _rubric_user_prompt(judge, context_packet),
                },
            ],
            "temperature": judge.get("temperature", 0.1),
        },
        RUBRIC_JUDGE_OUTPUT_SCHEMA,
    )
    if completion["status"] != "succeeded":
        return _invalid(
            trace["trace_id"],
            judge["judge_id"],
            judge.get("judge_version_id"),
            "invalid_structured_output",
            provider_metadata=_provider_metadata(completion, context_packet),
        )

    score = validate_judge_output(
        completion["value"],
        trace_id=trace["trace_id"],
        judge_id=judge["judge_id"],
        judge_version_id=judge.get("judge_version_id"),
        preserved_span_ids=set(context_packet["preserved_span_ids"]),
        require_span_citations=judge.get("require_span_citations", True),
    )
    score["cost"] = _provider_metadata(completion, context_packet)
    return score


def _invalid(
    trace_id: str,
    judge_id: str,
    judge_version_id: str | None,
    failure_mode: str,
    provider_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "score_id": new_id("score"),
        "trace_id": trace_id,
        "span_id": None,
        "judge_id": judge_id,
        "judge_version_id": judge_version_id,
        "status": "invalid_output",
        "failure_reason": "invalid_result",
        "value": None,
        "confidence": None,
        "reasoning": None,
        "evidence_span_ids": [],
        "failure_mode": failure_mode,
        "cost": provider_metadata,
        "latency_ms": None,
        "created_at": utc_now(),
    }


def _rubric_system_prompt(judge: dict[str, Any]) -> str:
    return (
        "You are an OpenABM rubric judge. Judge only the supplied trace context. "
        "Return structured JSON only. Use unsure when evidence is insufficient. "
        "Every behavioral claim must cite preserved span IDs. Do not cite omitted spans. "
        "Do not infer hidden user intent beyond the trace."
        f"\nJudge name: {judge.get('name', judge['judge_id'])}"
        f"\nDescription: {judge.get('description') or ''}"
    )


def _rubric_user_prompt(judge: dict[str, Any], context_packet: dict[str, Any]) -> str:
    return (
        "Apply this rubric to the trace context.\n"
        f"Rubric: {judge.get('rubric', {})}\n"
        f"Failure modes: {judge.get('failure_modes', [])}\n"
        "Trace context packet JSON:\n"
        f"{context_packet}"
    )


def _provider_metadata(
    completion: dict[str, Any],
    context_packet: dict[str, Any],
) -> dict[str, Any]:
    return {
        "provider": completion.get("provider"),
        "model": completion.get("model"),
        "usage": completion.get("usage"),
        "repaired": completion.get("repaired", False),
        "context_version": context_packet["context_version"],
        "context_packet_hash": context_packet.get("context_packet_hash"),
        "estimated_context_tokens": context_packet.get("estimated_tokens"),
        "truncation_notes": context_packet["truncation_notes"],
        "context_summaries": context_packet["summaries"],
        "preserved_span_ids": context_packet["preserved_span_ids"],
        "omitted_span_ids": context_packet["omitted_span_ids"],
    }
