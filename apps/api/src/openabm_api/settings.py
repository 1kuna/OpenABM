from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///.openabm/openabm.sqlite3"
    payload_dir: Path = Path(".openabm/payloads")
    environment: str = "local"
    auth_mode: str = "local"
    dev_api_key: str = "dev-openabm-key"
    allow_external_model_calls: bool = False
    incomplete_threshold_seconds: int = 300

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.getenv("OPENABM_DATABASE_URL", cls.database_url),
            payload_dir=Path(os.getenv("OPENABM_PAYLOAD_DIR", str(cls.payload_dir))),
            environment=os.getenv("OPENABM_ENV", cls.environment),
            auth_mode=os.getenv("OPENABM_AUTH_MODE", cls.auth_mode),
            dev_api_key=os.getenv("OPENABM_DEV_API_KEY", cls.dev_api_key),
            allow_external_model_calls=os.getenv(
                "OPENABM_ALLOW_EXTERNAL_MODEL_CALLS", "false"
            ).lower()
            == "true",
            incomplete_threshold_seconds=int(
                os.getenv("OPENABM_INCOMPLETE_THRESHOLD_SECONDS", "300")
            ),
        )

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("The local reference API currently supports sqlite:/// URLs only")
        return Path(self.database_url.removeprefix("sqlite:///"))

