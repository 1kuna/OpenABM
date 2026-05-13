from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///.openabm/openabm.sqlite3"
    payload_dir: Path = Path(".openabm/payloads")
    environment: str = "local"
    auth_mode: str = "local"
    dev_api_key: str = "dev-openabm-key"
    secret_mode: str = "local"
    secret_key: str | None = None
    external_secret_provider: str | None = None
    model_mode: str = "disabled"
    model_base_url: str = "http://127.0.0.1:1234/v1"
    model_api_key: str | None = None
    chat_model: str | None = None
    embedding_model: str | None = None
    model_context_length: int = 262144
    model_min_available_memory_mb: int = 8192
    allow_external_model_calls: bool = False
    judge_concurrency: int = 1
    embedding_concurrency: int = 1
    max_trace_tokens_for_judge: int = 262144
    incomplete_threshold_seconds: int = 300
    ingest_max_batch_items: int = 5000
    ingest_retryable_backpressure_items: int = 10000
    ingest_inline_payload_max_bytes: int = 262144
    ingest_max_events_per_span: int = 500
    ingest_stream_event_sample_rate: int = 10
    enable_external_notifications: bool = False
    enable_smtp_invites: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_starttls: bool = True
    smtp_timeout_seconds: float = 30.0
    cors_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            database_url=os.getenv("OPENABM_DATABASE_URL", cls.database_url),
            payload_dir=Path(os.getenv("OPENABM_PAYLOAD_DIR", str(cls.payload_dir))),
            environment=os.getenv("OPENABM_ENV", cls.environment),
            auth_mode=os.getenv("OPENABM_AUTH_MODE", cls.auth_mode),
            dev_api_key=os.getenv("OPENABM_DEV_API_KEY", cls.dev_api_key),
            secret_mode=os.getenv("OPENABM_SECRET_MODE", cls.secret_mode),
            secret_key=os.getenv("OPENABM_SECRET_KEY") or None,
            external_secret_provider=os.getenv("OPENABM_EXTERNAL_SECRET_PROVIDER") or None,
            model_mode=os.getenv("OPENABM_MODEL_MODE", cls.model_mode),
            model_base_url=os.getenv("OPENABM_MODEL_BASE_URL", cls.model_base_url),
            model_api_key=os.getenv("OPENABM_MODEL_API_KEY") or None,
            chat_model=os.getenv("OPENABM_CHAT_MODEL") or None,
            embedding_model=os.getenv("OPENABM_EMBEDDING_MODEL") or None,
            model_context_length=max(
                32768,
                int(os.getenv("OPENABM_MODEL_CONTEXT_LENGTH", str(cls.model_context_length))),
            ),
            model_min_available_memory_mb=max(
                0,
                int(
                    os.getenv(
                        "OPENABM_MODEL_MIN_AVAILABLE_MEMORY_MB",
                        str(cls.model_min_available_memory_mb),
                    )
                ),
            ),
            allow_external_model_calls=os.getenv(
                "OPENABM_ALLOW_EXTERNAL_MODEL_CALLS", "false"
            ).lower()
            == "true",
            judge_concurrency=int(os.getenv("OPENABM_JUDGE_CONCURRENCY", "1")),
            embedding_concurrency=int(os.getenv("OPENABM_EMBEDDING_CONCURRENCY", "1")),
            max_trace_tokens_for_judge=max(
                32768,
                int(
                    os.getenv(
                        "OPENABM_MAX_TRACE_TOKENS_FOR_JUDGE",
                        str(cls.max_trace_tokens_for_judge),
                    )
                ),
            ),
            incomplete_threshold_seconds=int(
                os.getenv("OPENABM_INCOMPLETE_THRESHOLD_SECONDS", "300")
            ),
            ingest_max_batch_items=int(os.getenv("OPENABM_INGEST_MAX_BATCH_ITEMS", "5000")),
            ingest_retryable_backpressure_items=int(
                os.getenv("OPENABM_INGEST_RETRYABLE_BACKPRESSURE_ITEMS", "10000")
            ),
            ingest_inline_payload_max_bytes=int(
                os.getenv("OPENABM_INGEST_INLINE_PAYLOAD_MAX_BYTES", "262144")
            ),
            ingest_max_events_per_span=int(
                os.getenv("OPENABM_INGEST_MAX_EVENTS_PER_SPAN", "500")
            ),
            ingest_stream_event_sample_rate=max(
                1,
                int(os.getenv("OPENABM_INGEST_STREAM_EVENT_SAMPLE_RATE", "10")),
            ),
            enable_external_notifications=os.getenv(
                "OPENABM_ENABLE_EXTERNAL_NOTIFICATIONS",
                "false",
            ).lower()
            == "true",
            enable_smtp_invites=os.getenv("OPENABM_ENABLE_SMTP_INVITES", "false").lower()
            == "true",
            smtp_host=os.getenv("OPENABM_SMTP_HOST") or None,
            smtp_port=int(os.getenv("OPENABM_SMTP_PORT", str(cls.smtp_port))),
            smtp_username=os.getenv("OPENABM_SMTP_USERNAME") or None,
            smtp_password=os.getenv("OPENABM_SMTP_PASSWORD") or None,
            smtp_from_email=os.getenv("OPENABM_SMTP_FROM_EMAIL") or None,
            smtp_use_starttls=os.getenv("OPENABM_SMTP_USE_STARTTLS", "true").lower()
            == "true",
            smtp_timeout_seconds=float(
                os.getenv("OPENABM_SMTP_TIMEOUT_SECONDS", str(cls.smtp_timeout_seconds))
            ),
            cors_origins=_csv_env(
                "OPENABM_CORS_ORIGINS",
                cls.cors_origins,
            ),
        )

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("The local reference API currently supports sqlite:/// URLs only")
        return Path(self.database_url.removeprefix("sqlite:///"))

    @property
    def model_endpoint_is_local(self) -> bool:
        parsed = urlparse(self.model_base_url)
        return parsed.hostname in {"127.0.0.1", "localhost", "::1"}


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name)
    if raw is None:
        return default
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    return values or default
