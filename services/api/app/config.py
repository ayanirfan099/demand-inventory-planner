"""Runtime configuration.

Everything is environment-driven so the same image runs locally, in Docker Compose and in
the test suite. Defaults are deliberately conservative: small uploads, short sessions and
an in-process worker for laptops.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORECASTOPS_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "ForecastOps API"

    database_url: str = "sqlite:///./data/local/forecastops.db"
    data_dir: Path = Path("./data/local")

    # Sessions
    session_cookie_name: str = "forecastops_session"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    # NoDecode keeps the raw comma-separated env value out of pydantic's JSON parser.
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Execution: "thread" runs jobs in-process (local/dev), "rq" enqueues to Redis,
    # "external" leaves jobs queued for a separate poller worker.
    execution_mode: Literal["thread", "rq", "external"] = "thread"
    redis_url: str = "redis://localhost:6379/0"
    job_queue_name: str = "forecastops"

    # Upload / job bounds
    max_upload_bytes: int = 5 * 1024 * 1024
    max_upload_rows: int = 200_000
    max_series: int = 200
    max_horizon_days: int = 90
    max_holdout_days: int = 90
    max_validation_folds: int = 5
    job_timeout_seconds: int = 300

    # Rate limits (requests per window)
    login_rate_limit: int = 10
    upload_rate_limit: int = 20
    job_rate_limit: int = 30
    rate_limit_window_seconds: int = 3600

    # Demo data
    demo_enabled: bool = True
    demo_email: str = "demo@forecastops.example"
    # Documented fictional demo password; override with FORECASTOPS_DEMO_PASSWORD.
    demo_password: str = "planning-demo-2024"  # noqa: S105
    demo_org_name: str = "Northwind Supply (demo)"
    demo_dataset_days: int = 365
    demo_seed: int = 20240517

    # Alerts
    stale_dataset_days: int = 30
    high_error_wape_threshold: float = 0.5

    log_level: str = "INFO"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand_path(cls, value):
        return Path(os.path.expanduser(str(value)))

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
