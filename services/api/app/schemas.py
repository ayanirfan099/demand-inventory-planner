"""Request models.

Every numeric and string bound here mirrors a bound enforced deeper in the stack (ingestion
limits, study config limits, policy limits); the API layer is the first line of defence,
not the only one.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MODEL_KEY = Literal["seasonal_naive", "hist_gradient_boosting"]
DEFAULT_MODEL_KEYS: tuple[MODEL_KEY, ...] = ("seasonal_naive", "hist_gradient_boosting")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned or " " in cleaned:
            raise ValueError("a valid email address is required")
        return cleaned


class SwitchOrgRequest(BaseModel):
    org_id: int = Field(gt=0)


class MembershipRoleRequest(BaseModel):
    role: Literal["owner", "analyst", "viewer"]


class SyntheticImportRequest(BaseModel):
    name: str = Field(default="Synthetic demo demand", min_length=1, max_length=160)
    days: int = Field(default=365, ge=60, le=730)
    seed: int = Field(default=20240517, ge=0, le=2**31 - 1)
    end_date: date | None = None


class SeriesUpdateRequest(BaseModel):
    on_hand: int = Field(ge=0, le=10_000_000)


class ForecastJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: int = Field(gt=0)
    dataset_version_id: int | None = Field(default=None, gt=0)
    horizon_days: int = Field(default=14, ge=1, le=90)
    holdout_days: int = Field(default=14, ge=7, le=90)
    validation_folds: int = Field(default=2, ge=0, le=5)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    model_keys: list[MODEL_KEY] = Field(default_factory=lambda: list(DEFAULT_MODEL_KEYS))
    model_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=120)

    @field_validator("model_keys")
    @classmethod
    def _dedupe_models(cls, value: list[MODEL_KEY]) -> list[MODEL_KEY]:
        if not value:
            raise ValueError("at least one model is required")
        seen: list[MODEL_KEY] = []
        for key in value:
            if key not in seen:
                seen.append(key)
        return seen


class InventoryPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=160)
    lead_time_days: int = Field(default=14, ge=0, le=365)
    review_period_days: int = Field(default=7, ge=1, le=180)
    service_level: float = Field(default=0.95, gt=0.5, lt=0.999)
    min_order_qty: int = Field(default=0, ge=0, le=1_000_000)
    pack_size: int = Field(default=1, ge=1, le=10_000)
    notes: str | None = Field(default=None, max_length=2000)


class InventoryPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    review_period_days: int | None = Field(default=None, ge=1, le=180)
    service_level: float | None = Field(default=None, gt=0.5, lt=0.999)
    min_order_qty: int | None = Field(default=None, ge=0, le=1_000_000)
    pack_size: int | None = Field(default=None, ge=1, le=10_000)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class SuggestRequest(BaseModel):
    run_id: int = Field(gt=0)


class SuggestionStatusRequest(BaseModel):
    status: Literal["acknowledged", "dismissed"]


class AlertStatusRequest(BaseModel):
    status: Literal["acknowledged", "resolved"]
