from __future__ import annotations

import json
import os
import time

from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore

from openabm_worker.retention import run_retention_once


def main() -> None:
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    worker_id = os.environ.get("OPENABM_WORKER_ID", "local-retention-worker")
    project_id = os.environ.get("OPENABM_WORKER_PROJECT_ID") or None
    interval_seconds = max(1, int(os.environ.get("OPENABM_WORKER_INTERVAL_SECONDS", "300")))
    dry_run = os.environ.get("OPENABM_RETENTION_DRY_RUN", "true").lower() != "false"
    print(
        json.dumps(
            {
                "status": "started",
                "worker_id": worker_id,
                "worker_type": "retention",
                "project_id": project_id,
                "interval_seconds": interval_seconds,
                "dry_run": dry_run,
            },
            sort_keys=True,
        )
    )
    while True:
        result = run_retention_once(
            store,
            project_id=project_id,
            dry_run=dry_run,
            worker_id=worker_id,
        )
        print(json.dumps(result, sort_keys=True))
        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
