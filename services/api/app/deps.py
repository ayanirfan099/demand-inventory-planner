"""Authentication, organization scoping and role checks.

All tenant access funnels through the helpers here so that no router can accidentally
query another organization's rows. Missing rows are reported as 404 rather than 403 so an
attacker cannot probe which ids exist in another tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .errors import ForbiddenError, NotFoundError, UnauthorizedError
from .models import (
    ROLE_RANK,
    Dataset,
    DatasetVersion,
    ForecastJob,
    ForecastRun,
    InventoryPolicy,
    Membership,
    Organization,
    SessionToken,
    User,
    utcnow,
)
from .security import hash_token


@dataclass(frozen=True)
class AuthContext:
    user: User
    org: Organization
    role: str
    session: SessionToken

    @property
    def org_id(self) -> int:
        return self.org.id

    def has_role(self, minimum: str) -> bool:
        return ROLE_RANK.get(self.role, 0) >= ROLE_RANK[minimum]


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def get_session_token(request: Request, db: Session = Depends(get_db)) -> SessionToken:
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        raise UnauthorizedError("Sign in to continue.")
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_token(raw)))
    if session is None:
        raise UnauthorizedError("Your session is no longer valid. Sign in again.")
    if _aware(session.expires_at) <= datetime.now(UTC):
        db.delete(session)
        raise UnauthorizedError("Your session expired. Sign in again.")
    session.last_seen_at = utcnow()
    return session


def get_auth(
    session: SessionToken = Depends(get_session_token),
    db: Session = Depends(get_db),
) -> AuthContext:
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Sign in to continue.")

    membership: Membership | None = None
    if session.active_org_id:
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.org_id == session.active_org_id,
            )
        )
    if membership is None:
        # Fall back to the first membership so a stale active_org_id cannot lock a user out.
        membership = db.scalar(
            select(Membership).where(Membership.user_id == user.id).order_by(Membership.id)
        )
        if membership is not None:
            session.active_org_id = membership.org_id
    if membership is None:
        raise ForbiddenError("Your account is not a member of any organization.")

    org = db.get(Organization, membership.org_id)
    if org is None:
        raise ForbiddenError("Your organization is no longer available.")
    return AuthContext(user=user, org=org, role=membership.role, session=session)


def require_role(minimum: str):
    """Dependency factory enforcing a minimum role."""

    def _dependency(auth: AuthContext = Depends(get_auth)) -> AuthContext:
        if not auth.has_role(minimum):
            raise ForbiddenError(f"This action requires the {minimum} role.")
        return auth

    return _dependency


viewer_auth = Depends(get_auth)
analyst_auth = Depends(require_role("analyst"))
owner_auth = Depends(require_role("owner"))


# --- Tenant-scoped lookups ---------------------------------------------------------------


def get_dataset(db: Session, auth: AuthContext, dataset_id: int) -> Dataset:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.org_id == auth.org_id))
    if dataset is None:
        raise NotFoundError("Dataset not found.")
    return dataset


def get_dataset_version(db: Session, auth: AuthContext, version_id: int) -> DatasetVersion:
    version = db.scalar(
        select(DatasetVersion).where(DatasetVersion.id == version_id, DatasetVersion.org_id == auth.org_id)
    )
    if version is None:
        raise NotFoundError("Dataset version not found.")
    return version


def get_job(db: Session, auth: AuthContext, job_id: int) -> ForecastJob:
    job = db.scalar(select(ForecastJob).where(ForecastJob.id == job_id, ForecastJob.org_id == auth.org_id))
    if job is None:
        raise NotFoundError("Forecast job not found.")
    return job


def get_run(db: Session, auth: AuthContext, run_id: int) -> ForecastRun:
    run = db.scalar(select(ForecastRun).where(ForecastRun.id == run_id, ForecastRun.org_id == auth.org_id))
    if run is None:
        raise NotFoundError("Forecast run not found.")
    return run


def get_policy(db: Session, auth: AuthContext, policy_id: int) -> InventoryPolicy:
    policy = db.scalar(
        select(InventoryPolicy).where(InventoryPolicy.id == policy_id, InventoryPolicy.org_id == auth.org_id)
    )
    if policy is None:
        raise NotFoundError("Inventory policy not found.")
    return policy
