"""Alerts derived from datasets, jobs, forecast quality and inventory exposure."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, get_auth, require_role
from ..errors import NotFoundError
from ..models import Alert, utcnow
from ..schemas import AlertStatusRequest
from ..serializers import alert as serialize_alert
from ..serializers import iso
from ..services import alerts as alert_service
from ..services import audit

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    status_filter: str = Query(default="open", alias="status", pattern="^(open|acknowledged|resolved|all)$"),
    limit: int = Query(default=50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth),
    db: Session = Depends(get_db),
) -> dict:
    # Rules are evaluated on read so a fresh dataset or failed job surfaces immediately,
    # even without a scheduler. Every rule is deduplicated, so this is safe to call often.
    alert_service.refresh_org(db, auth.org_id)
    db.flush()

    query = select(Alert).where(Alert.org_id == auth.org_id)
    if status_filter != "all":
        query = query.where(Alert.status == status_filter)
    rows = db.scalars(query.order_by(Alert.id.desc()).limit(limit)).all()

    counts = {"open": 0, "acknowledged": 0, "resolved": 0}
    for row in db.scalars(select(Alert).where(Alert.org_id == auth.org_id)).all():
        counts[row.status] = counts.get(row.status, 0) + 1

    return {
        "alerts": [serialize_alert(row) for row in rows],
        "counts": counts,
        "thresholds": {"high_error_wape": 0.5},
    }


@router.post("/{alert_id}/status")
def update_alert_status(
    alert_id: int,
    payload: AlertStatusRequest,
    auth: AuthContext = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
) -> dict:
    alert = db.scalar(select(Alert).where(Alert.id == alert_id, Alert.org_id == auth.org_id))
    if alert is None:
        raise NotFoundError("Alert not found.")
    alert.status = payload.status
    if payload.status == "acknowledged":
        alert.acknowledged_at = utcnow()
        alert.acknowledged_by_id = auth.user.id
    db.add(alert)
    audit.record(
        db,
        org_id=auth.org_id,
        action="alert.status_changed",
        entity_type="alert",
        entity_id=alert.id,
        actor_user_id=auth.user.id,
        payload={"kind": alert.kind, "status": payload.status},
    )
    db.flush()
    return {"alert": serialize_alert(alert), "updated_at": iso(utcnow())}
