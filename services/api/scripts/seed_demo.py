"""Seed a fictional demo organization, users and data.

Idempotent: re-running it reuses existing organizations/users and only adds a new dataset
version when the generated content actually changed.

Everything created here is synthetic. The credentials are fictional demo logins, printed
to stdout and documented in the README so reviewers can sign in; they are not secrets.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.config import settings  # noqa: E402
from app.db import session_scope  # noqa: E402
from app.models import (  # noqa: E402
    Dataset,
    ForecastJob,
    ForecastRun,
    InventoryPolicy,
    Membership,
    Organization,
    ReorderSuggestion,
    User,
)
from app.security import hash_password  # noqa: E402
from app.services import ingestion, inventory, storage  # noqa: E402
from forecastops_forecasting import generate_demo_demand, normalize_demand  # noqa: E402
from sqlalchemy import select  # noqa: E402

DEMO_PASSWORDS = {
    "demo@forecastops.example": settings.demo_password,
    "analyst@forecastops.example": "analyst-demo-2024",
    "viewer@forecastops.example": "viewer-demo-2024",
    "cascade@forecastops.example": "cascade-demo-2024",
}

DEMO_USERS = [
    ("demo@forecastops.example", "Ada Lovelace (demo owner)", "owner"),
    ("analyst@forecastops.example", "Grace Hopper (demo analyst)", "analyst"),
    ("viewer@forecastops.example", "Katherine Johnson (demo viewer)", "viewer"),
]

CASCADE_USERS = [("cascade@forecastops.example", "Cascade Owner (second tenant)", "owner")]

FICTIONAL_NOTICE = (
    "All organizations, stores, items and demand in this deployment are fictional and synthetic."
)


def _ensure_org(session, name: str, slug: str) -> Organization:
    org = session.scalar(select(Organization).where(Organization.slug == slug))
    if org is None:
        org = Organization(name=name, slug=slug)
        session.add(org)
        session.flush()
    return org


def _ensure_user(session, email: str, display_name: str, password: str) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            display_name=display_name,
            password_hash=hash_password(password),
            is_demo=True,
        )
        session.add(user)
        session.flush()
    return user


def _ensure_membership(session, user: User, org: Organization, role: str) -> None:
    membership = session.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.org_id == org.id)
    )
    if membership is None:
        session.add(Membership(user_id=user.id, org_id=org.id, role=role))
        session.flush()
    elif membership.role != role:
        membership.role = role
        session.add(membership)


def _import_dataset(session, org: Organization, user: User, *, days: int, stores, items, seed: int):
    frame = generate_demo_demand(days=days, seed=seed, stores=stores, items=items, end_date=date.today())
    clean, report = normalize_demand(frame, max_series=settings.max_series)
    quality = report.as_dict()
    quality["synthetic"] = True
    quality["notice"] = (
        "Synthetic demo data. Any metric derived from it is a smoke result, not a benchmark of "
        "real-world forecasting performance."
    )
    result = ingestion.import_demand(
        session,
        org_id=org.id,
        user_id=user.id,
        name="Synthetic demo demand",
        description="Seeded synthetic daily demand for three stores and four items.",
        frame=clean,
        quality=quality,
        source="synthetic",
    )
    return result.dataset, result.version, result.created


def _run_demo_job(session, org: Organization, user: User, dataset: Dataset):

    job = ForecastJob(
        org_id=org.id,
        dataset_id=dataset.id,
        dataset_version_id=dataset.current_version_id,
        status="queued",
        stage="queued",
        horizon_days=14,
        holdout_days=14,
        validation_folds=2,
        seed=42,
        model_keys=["seasonal_naive", "hist_gradient_boosting"],
        model_params={},
        idempotency_key=f"seed-job-{org.slug}-v{dataset.current_version_id}",
        attempt=1,
        created_by_id=user.id,
    )
    session.add(job)
    session.flush()
    return job.id


def seed(days: int = 365, *, with_runs: bool = True) -> dict:
    summary: dict[str, object] = {}
    with session_scope() as session:
        org = _ensure_org(session, settings.demo_org_name, "northwind-demo")
        demo_user = None
        for email, display_name, role in DEMO_USERS:
            user = _ensure_user(session, email, display_name, DEMO_PASSWORDS[email])
            _ensure_membership(session, user, org, role)
            if role == "owner":
                demo_user = user
        assert demo_user is not None

        cascade_org = _ensure_org(session, "Cascade Outfitters", "cascade-outfitters")
        for email, display_name, role in CASCADE_USERS:
            user = _ensure_user(session, email, display_name, DEMO_PASSWORDS[email])
            _ensure_membership(session, user, cascade_org, role)
        cascade_owner = session.scalar(select(User).where(User.email == CASCADE_USERS[0][0]))

        dataset, version, created = _import_dataset(
            session,
            org,
            demo_user,
            days=days,
            stores=("north-dock", "river-bend", "harbour-hill"),
            items=("coffee-beans", "paper-cups", "oat-milk", "cold-brew"),
            seed=settings.demo_seed,
        )
        cascade_dataset, cascade_version, cascade_created = _import_dataset(
            session,
            cascade_org,
            cascade_owner,
            days=180,
            stores=("cascade-flagship",),
            items=("trail-mix", "water-filter"),
            seed=settings.demo_seed + 7,
        )

        job_id = None
        if with_runs:
            existing_job = session.scalar(
                select(ForecastJob).where(
                    ForecastJob.org_id == org.id,
                    ForecastJob.idempotency_key == f"seed-job-{org.slug}-v{dataset.current_version_id}",
                )
            )
            if existing_job is None:
                job_id = _run_demo_job(session, org, demo_user, dataset)
            else:
                job_id = existing_job.id if existing_job.status != "succeeded" else None

        summary.update(
            {
                "org": org.slug,
                "dataset_id": dataset.id,
                "dataset_version": version.version,
                "dataset_created": created,
                "cascade_dataset_id": cascade_dataset.id,
                "cascade_version": cascade_version.version,
                "cascade_created": cascade_created,
                "job_id": job_id,
            }
        )

    # The runner opens its own sessions, so it runs after the seeding transaction commits.
    if with_runs and summary.get("job_id"):
        from app.services.runner import run_forecast_job

        run_forecast_job(int(summary["job_id"]))  # type: ignore[arg-type]

    with session_scope() as session:
        org = session.scalar(select(Organization).where(Organization.slug == "northwind-demo"))
        dataset = session.scalar(
            select(Dataset).where(Dataset.org_id == org.id, Dataset.name == "Synthetic demo demand")
        )
        policy = session.scalar(
            select(InventoryPolicy).where(
                InventoryPolicy.dataset_id == dataset.id, InventoryPolicy.name == "Standard weekly review"
            )
        )
        if policy is None:
            policy = InventoryPolicy(
                org_id=org.id,
                dataset_id=dataset.id,
                name="Standard weekly review",
                lead_time_days=14,
                review_period_days=7,
                service_level=0.95,
                min_order_qty=12,
                pack_size=6,
                notes="Demo policy: 14-day supplier lead time, weekly review, 95% service level.",
                created_by_id=session.scalar(select(User).where(User.email == DEMO_USERS[0][0])).id,
            )
            session.add(policy)
            session.flush()

        run = session.scalar(
            select(ForecastRun)
            .where(ForecastRun.org_id == org.id, ForecastRun.is_selected.is_(True))
            .order_by(ForecastRun.id.desc())
        )
        has_suggestions = session.scalar(
            select(ReorderSuggestion.id).where(ReorderSuggestion.policy_id == policy.id).limit(1)
        )
        if run is not None and has_suggestions is None:
            owner = session.scalar(select(User).where(User.email == DEMO_USERS[0][0]))
            inventory.generate_suggestions(session, org_id=org.id, user_id=owner.id, policy=policy, run=run)
        summary["policy_id"] = policy.id

    storage.sweep_previews()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed fictional demo data for ForecastOps")
    parser.add_argument("--days", type=int, default=settings.demo_dataset_days)
    parser.add_argument("--no-runs", action="store_true", help="Skip the demo forecast run")
    args = parser.parse_args()

    summary = seed(days=args.days, with_runs=not args.no_runs)
    print()
    print("ForecastOps demo seeded")
    print("-----------------------")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print()
    print("Sign in with a fictional demo account:")
    for email, password in DEMO_PASSWORDS.items():
        print(f"  {email}  /  {password}")
    print()
    print(FICTIONAL_NOTICE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
