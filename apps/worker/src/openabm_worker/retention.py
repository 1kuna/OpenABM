from __future__ import annotations

from typing import Any


def run_retention_once(
    store: Any,
    *,
    project_id: str | None = None,
    dry_run: bool = True,
    worker_id: str = "local-retention-worker",
) -> dict[str, Any]:
    projects = (
        [{"project_id": project_id}]
        if project_id
        else [{"project_id": project["project_id"]} for project in store.list_projects()]
    )
    heartbeat = store.record_worker_heartbeat(
        {
            "worker_id": worker_id,
            "project_id": project_id,
            "worker_type": "retention",
            "status": "running",
            "queue_depth": 0,
            "details": {"dry_run": dry_run, "project_count": len(projects)},
        }
    )
    results = []
    errors = []
    for project in projects:
        current_project_id = project["project_id"]
        policies = [
            policy
            for policy in store.list_retention_policies(current_project_id)
            if policy["status"] == "active"
        ]
        for policy in policies:
            try:
                result = store.apply_retention_policy(
                    current_project_id,
                    policy["retention_policy_id"],
                    dry_run=dry_run,
                )
                store.append_audit(
                    "apply_retention_policy",
                    "retention_policy",
                    current_project_id,
                    policy["retention_policy_id"],
                    {
                        "source": "retention_worker",
                        "worker_id": worker_id,
                        "dry_run": dry_run,
                        "candidate_count": len(result["candidate_trace_ids"]),
                        "deleted_count": len(result["deleted_trace_ids"]),
                    },
                )
                results.append(result)
            except Exception as exc:  # pragma: no cover - surfaced in result for operators.
                errors.append(
                    {
                        "project_id": current_project_id,
                        "retention_policy_id": policy["retention_policy_id"],
                        "error": str(exc),
                    }
                )
    status = "succeeded" if not errors else "partial_failure"
    heartbeat = store.record_worker_heartbeat(
        {
            "worker_id": worker_id,
            "project_id": project_id,
            "worker_type": "retention",
            "status": "ok" if not errors else "error",
            "queue_depth": 0,
            "details": {
                "dry_run": dry_run,
                "applied_policy_count": len(results),
                "error_count": len(errors),
            },
        }
    )
    return {
        "status": status,
        "dry_run": dry_run,
        "worker_id": worker_id,
        "heartbeat": heartbeat,
        "project_count": len(projects),
        "policy_count": len(results),
        "candidate_trace_count": sum(len(result["candidate_trace_ids"]) for result in results),
        "deleted_trace_count": sum(len(result["deleted_trace_ids"]) for result in results),
        "results": results,
        "errors": errors,
    }
