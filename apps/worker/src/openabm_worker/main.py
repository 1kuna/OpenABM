from __future__ import annotations

import time

from openabm_api.settings import Settings
from openabm_api.storage import SQLiteStore


def main() -> None:
    settings = Settings.from_env()
    store = SQLiteStore(settings.sqlite_path)
    store.init_db()
    print("OpenABM worker scaffold started. No model-backed jobs are enabled.")
    while True:
        time.sleep(5)


if __name__ == "__main__":
    main()

