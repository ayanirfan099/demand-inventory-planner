"""Persistence model.

Every tenant-owned row carries ``org_id`` and every query path filters on it. The only
global tables are ``users`` and ``sessions`` (a user can belong to several organizations).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


ROLES = ("owner", "analyst", "viewer")
ROLE_RANK = {"viewer": 1, "analyst": 2, "owner": 3}

JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
ALERT_STATUSES = ("open", "acknowledged", "resolved")
SUGGESTION_STATUSES = ("open", "acknowledged", "dismissed")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list[Membership]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "org_id", name="uq_membership_user_org"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship()


class SessionToken(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    active_org_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship()


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_dataset_org_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="upload")  # upload | synthetic
    original_filename: Mapped[str | None] = mapped_column(String(255))
    current_version_id: Mapped[int | None] = mapped_column(Integer)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list[DatasetVersion]] = relationship(
        back_populates="dataset", order_by="DatasetVersion.version", foreign_keys="DatasetVersion.dataset_id"
    )


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version", name="uq_dataset_version"),
        UniqueConstraint("dataset_id", "fingerprint", name="uq_dataset_fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(80), index=True)
    row_count: Mapped[int] = mapped_column(Integer)
    series_count: Mapped[int] = mapped_column(Integer)
    date_min: Mapped[date] = mapped_column(Date)
    date_max: Mapped[date] = mapped_column(Date)
    storage_path: Mapped[str] = mapped_column(String(500))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    dataset: Mapped[Dataset] = relationship(back_populates="versions", foreign_keys=[dataset_id])


class SeriesDefinition(Base):
    __tablename__ = "series_definitions"
    __table_args__ = (UniqueConstraint("dataset_id", "store", "item", name="uq_series_dataset_store_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    store: Mapped[str] = mapped_column(String(120))
    item: Mapped[str] = mapped_column(String(120))
    on_hand: Mapped[int | None] = mapped_column(Integer)
    on_hand_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActualObservation(Base):
    """Daily observed demand for a dataset version (used for actual-vs-forecast views)."""

    __tablename__ = "actual_observations"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "series_id", "observed_on", name="uq_actual_version_series_date"),
        Index("ix_actual_version_date", "dataset_version_id", "observed_on"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"))
    series_id: Mapped[int] = mapped_column(ForeignKey("series_definitions.id", ondelete="CASCADE"))
    observed_on: Mapped[date] = mapped_column(Date)
    quantity: Mapped[float] = mapped_column(Float)


class ModelConfiguration(Base):
    __tablename__ = "model_configurations"
    __table_args__ = (UniqueConstraint("org_id", "key", "name", name="uq_model_config"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastJob(Base):
    __tablename__ = "forecast_jobs"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key", name="uq_job_idempotency"),
        Index("ix_job_org_created", "org_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    stage: Mapped[str | None] = mapped_column(String(80))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    horizon_days: Mapped[int] = mapped_column(Integer, default=14)
    holdout_days: Mapped[int] = mapped_column(Integer, default=14)
    validation_folds: Mapped[int] = mapped_column(Integer, default=2)
    seed: Mapped[int] = mapped_column(Integer, default=42)
    model_keys: Mapped[list] = mapped_column(JSON, default=list)
    model_params: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    parent_job_id: Mapped[int | None] = mapped_column(ForeignKey("forecast_jobs.id", ondelete="SET NULL"))
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(String(500))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ForecastRun(Base):
    __tablename__ = "forecast_runs"
    __table_args__ = (UniqueConstraint("job_id", "model_key", name="uq_run_job_model"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("forecast_jobs.id", ondelete="CASCADE"), index=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"))
    model_key: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(160))
    model_config: Mapped[dict] = mapped_column(JSON, default=dict)
    forecast_mode: Mapped[str] = mapped_column(String(64))
    forecast_mode_label: Mapped[str] = mapped_column(Text)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    seed: Mapped[int] = mapped_column(Integer, default=42)
    train_start: Mapped[date | None] = mapped_column(Date)
    train_end: Mapped[date | None] = mapped_column(Date)
    test_start: Mapped[date | None] = mapped_column(Date)
    test_end: Mapped[date | None] = mapped_column(Date)
    horizon_days: Mapped[int] = mapped_column(Integer, default=14)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    validation_folds: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastPoint(Base):
    __tablename__ = "forecast_points"
    __table_args__ = (
        Index("ix_point_run_kind_date", "run_id", "kind", "target_date"),
        Index("ix_point_run_series", "run_id", "series_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"))
    series_id: Mapped[int] = mapped_column(ForeignKey("series_definitions.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # holdout | forecast
    target_date: Mapped[date] = mapped_column(Date)
    horizon_step: Mapped[int] = mapped_column(Integer)
    forecast: Mapped[float] = mapped_column(Float)
    actual: Mapped[float | None] = mapped_column(Float)
    lower: Mapped[float | None] = mapped_column(Float)
    upper: Mapped[float | None] = mapped_column(Float)


class MetricResult(Base):
    __tablename__ = "metric_results"
    __table_args__ = (
        Index("ix_metric_run_scope", "run_id", "scope"),
        UniqueConstraint("run_id", "scope", "series_id", "metric", name="uq_metric_run_scope_series_metric"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(16))  # aggregate | series
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series_definitions.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(32))
    value: Mapped[float | None] = mapped_column(Float)


class InventoryPolicy(Base):
    __tablename__ = "inventory_policies"
    __table_args__ = (UniqueConstraint("dataset_id", "name", name="uq_policy_dataset_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    lead_time_days: Mapped[int] = mapped_column(Integer, default=14)
    review_period_days: Mapped[int] = mapped_column(Integer, default=7)
    service_level: Mapped[float] = mapped_column(Float, default=0.95)
    min_order_qty: Mapped[int] = mapped_column(Integer, default=0)
    pack_size: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReorderSuggestion(Base):
    __tablename__ = "reorder_suggestions"
    __table_args__ = (Index("ix_suggestion_policy_created", "policy_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("inventory_policies.id", ondelete="CASCADE"), index=True)
    series_id: Mapped[int] = mapped_column(ForeignKey("series_definitions.id", ondelete="CASCADE"))
    run_id: Mapped[int] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="open")
    horizon_days: Mapped[int] = mapped_column(Integer)
    on_hand: Mapped[float] = mapped_column(Float)
    forecast_demand: Mapped[float] = mapped_column(Float)
    safety_stock: Mapped[float] = mapped_column(Float)
    reorder_point: Mapped[float] = mapped_column(Float)
    target_level: Mapped[float] = mapped_column(Float)
    projected_on_hand: Mapped[float] = mapped_column(Float)
    shortage: Mapped[float] = mapped_column(Float)
    suggested_qty_raw: Mapped[float] = mapped_column(Float)
    suggested_qty_rounded: Mapped[int] = mapped_column(Integer)
    assumptions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alert_org_status", "org_id", "status"),
        UniqueConstraint("org_id", "dedupe_key", name="uq_alert_dedupe"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(48))
    severity: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("forecast_jobs.id", ondelete="CASCADE"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"))
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series_definitions.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ReportExport(Base):
    __tablename__ = "report_exports"
    __table_args__ = (Index("ix_export_org_created", "org_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(48))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("forecast_runs.id", ondelete="CASCADE"))
    dataset_version_id: Mapped[int | None] = mapped_column(ForeignKey("dataset_versions.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(80))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ready")
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_org_created", "org_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(48))
    entity_id: Mapped[str | None] = mapped_column(String(48))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
