"""Inventory policy configuration and reorder decision support."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth, get_dataset, get_policy, get_run, require_role
from ..errors import ConflictError, NotFoundError
from ..models import (
    ForecastRun,
    InventoryPolicy,
    ReorderSuggestion,
    SeriesDefinition,
)
from ..schemas import (
    InventoryPolicyCreate,
    InventoryPolicyUpdate,
    SuggestionStatusRequest,
    SuggestRequest,
)
from ..serializers import iso
from ..serializers import policy as serialize_policy
from ..serializers import suggestion as serialize_suggestion
from ..services import audit, inventory

router = APIRouter(tags=["inventory"])


@router.post("/inventory-policies", status_code=status.HTTP_201_CREATED)
def create_policy(
    payload: InventoryPolicyCreate,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    dataset = get_dataset(db, auth, payload.dataset_id)
    duplicate = db.scalar(
        select(InventoryPolicy).where(
            InventoryPolicy.dataset_id == dataset.id, InventoryPolicy.name == payload.name
        )
    )
    if duplicate is not None:
        raise ConflictError("A policy with that name already exists for this dataset.")
    policy = InventoryPolicy(
        org_id=auth.org_id,
        dataset_id=dataset.id,
        name=payload.name.strip(),
        lead_time_days=payload.lead_time_days,
        review_period_days=payload.review_period_days,
        service_level=payload.service_level,
        min_order_qty=payload.min_order_qty,
        pack_size=payload.pack_size,
        notes=(payload.notes or "").strip() or None,
        created_by_id=auth.user.id,
    )
    db.add(policy)
    db.flush()
    audit.record(
        db,
        org_id=auth.org_id,
        action="inventory_policy.created",
        entity_type="inventory_policy",
        entity_id=policy.id,
        actor_user_id=auth.user.id,
        payload={
            "dataset_id": dataset.id,
            "lead_time_days": policy.lead_time_days,
            "review_period_days": policy.review_period_days,
            "service_level": policy.service_level,
            "min_order_qty": policy.min_order_qty,
            "pack_size": policy.pack_size,
        },
    )
    return {"policy": serialize_policy(policy)}


@router.get("/inventory-policies")
def list_policies(
    dataset_id: int | None = Query(default=None, gt=0),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    query = select(InventoryPolicy).where(InventoryPolicy.org_id == auth.org_id)
    if dataset_id is not None:
        dataset = get_dataset(db, auth, dataset_id)
        query = query.where(InventoryPolicy.dataset_id == dataset.id)
    rows = db.scalars(query.order_by(InventoryPolicy.id.desc())).all()
    return {"policies": [serialize_policy(row) for row in rows]}


@router.get("/inventory-policies/{policy_id}")
def get_policy_detail(
    policy_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    policy = get_policy(db, auth, policy_id)
    suggestions = db.execute(
        select(ReorderSuggestion, SeriesDefinition)
        .join(SeriesDefinition, ReorderSuggestion.series_id == SeriesDefinition.id)
        .where(ReorderSuggestion.policy_id == policy.id)
        .order_by(ReorderSuggestion.id.desc())
        .limit(300)
    ).all()
    return {
        "policy": serialize_policy(policy),
        "suggestions": [serialize_suggestion(row, series_row) for row, series_row in suggestions],
        "formula": {
            "text": (
                "reorder_point = forecast demand over (lead time + review period) "
                "+ z * sigma_holdout * sqrt(window)"
            ),
            "notes": [
                "z is the normal quantile of the configured service level.",
                "sigma_holdout is the standard deviation of the selected model's holdout residuals for the series.",
                "Quantities are raised to the minimum order quantity and then rounded up to whole packs.",
                "Suggestions are decision support only; nothing is ordered automatically.",
            ],
        },
    }


@router.patch("/inventory-policies/{policy_id}")
def update_policy(
    policy_id: int,
    payload: InventoryPolicyUpdate,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    policy = get_policy(db, auth, policy_id)
    before = serialize_policy(policy)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for field, value in changes.items():
        setattr(policy, field, value.strip() if isinstance(value, str) else value)
    db.add(policy)
    audit.record(
        db,
        org_id=auth.org_id,
        action="inventory_policy.updated",
        entity_type="inventory_policy",
        entity_id=policy.id,
        actor_user_id=auth.user.id,
        payload={"before": before, "changes": changes},
    )
    db.flush()
    return {"policy": serialize_policy(policy)}


@router.post("/inventory-policies/{policy_id}/suggestions", status_code=status.HTTP_201_CREATED)
def create_suggestions(
    policy_id: int,
    payload: SuggestRequest,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    policy = get_policy(db, auth, policy_id)
    run = get_run(db, auth, payload.run_id)

    if run.dataset_version_id != _current_version(db, policy):
        raise ConflictError("This run was produced from a different dataset version than the policy targets.")

    suggestions = inventory.generate_suggestions(
        db, org_id=auth.org_id, user_id=auth.user.id, policy=policy, run=run
    )
    series_index = {
        row.id: row
        for row in db.scalars(
            select(SeriesDefinition).where(SeriesDefinition.dataset_id == policy.dataset_id)
        )
    }
    payload_rows = [serialize_suggestion(row, series_index.get(row.series_id)) for row in suggestions]
    return {
        "policy": serialize_policy(policy),
        "run_id": run.id,
        "suggestions": payload_rows,
        "summary": {
            "series": len(payload_rows),
            "series_with_order": sum(1 for row in payload_rows if row["suggested_qty"] > 0),
            "total_units": sum(row["suggested_qty"] for row in payload_rows),
        },
        "disclaimer": (
            "Decision support only. Nothing is ordered automatically and service levels are planning inputs, "
            "not guarantees. Verify on-hand quantities before acting."
        ),
    }


def _current_version(db: Session, policy: InventoryPolicy) -> int | None:
    from ..models import Dataset

    dataset = db.get(Dataset, policy.dataset_id)
    return dataset.current_version_id if dataset else None


@router.get("/inventory-suggestions")
def list_suggestions(
    policy_id: int | None = Query(default=None, gt=0),
    run_id: int | None = Query(default=None, gt=0),
    only_orders: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    query = (
        select(ReorderSuggestion, SeriesDefinition, InventoryPolicy)
        .join(SeriesDefinition, ReorderSuggestion.series_id == SeriesDefinition.id)
        .join(InventoryPolicy, ReorderSuggestion.policy_id == InventoryPolicy.id)
        .where(ReorderSuggestion.org_id == auth.org_id)
    )
    if policy_id is not None:
        query = query.where(ReorderSuggestion.policy_id == policy_id)
    if run_id is not None:
        query = query.where(ReorderSuggestion.run_id == run_id)
    if only_orders:
        query = query.where(ReorderSuggestion.suggested_qty_rounded > 0)
    rows = db.execute(query.order_by(ReorderSuggestion.id.desc()).limit(limit)).all()
    return {
        "suggestions": [
            {**serialize_suggestion(row, series_row), "policy_name": policy_row.name}
            for row, series_row, policy_row in rows
        ]
    }


@router.patch("/inventory-suggestions/{suggestion_id}")
def update_suggestion(
    suggestion_id: int,
    payload: SuggestionStatusRequest,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    suggestion = db.scalar(
        select(ReorderSuggestion).where(
            ReorderSuggestion.id == suggestion_id, ReorderSuggestion.org_id == auth.org_id
        )
    )
    if suggestion is None:
        raise NotFoundError("Suggestion not found.")
    previous = suggestion.status
    suggestion.status = payload.status
    db.add(suggestion)
    audit.record(
        db,
        org_id=auth.org_id,
        action="reorder_suggestion.status_changed",
        entity_type="reorder_suggestion",
        entity_id=suggestion.id,
        actor_user_id=auth.user.id,
        payload={"from": previous, "to": payload.status, "suggested_qty": suggestion.suggested_qty_rounded},
    )
    db.flush()
    series_row = db.get(SeriesDefinition, suggestion.series_id)
    return {"suggestion": serialize_suggestion(suggestion, series_row)}


@router.get("/inventory-policies/{policy_id}/latest-run")
def latest_run_for_policy(
    policy_id: int,
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    policy = get_policy(db, auth, policy_id)
    latest = db.scalars(
        select(ForecastRun)
        .where(ForecastRun.org_id == auth.org_id, ForecastRun.is_selected.is_(True))
        .order_by(ForecastRun.id.desc())
        .limit(10)
    ).all()
    version_id = _current_version(db, policy)
    for run in latest:
        if run.dataset_version_id == version_id:
            return {
                "run_id": run.id,
                "model_key": run.model_key,
                "label": run.label,
                "created_at": iso(run.created_at),
            }
    raise NotFoundError("No completed forecast run exists for this dataset version yet.")
