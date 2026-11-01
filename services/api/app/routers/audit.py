"""Audit trail and export history (owner-visible)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import AuthContext, require_role
from ..models import ReportExport
from ..serializers import audit_event, iso
from ..services import audit

router = APIRouter(tags=["audit"])


@router.get("/audit-events")
def list_audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None, max_length=64),
    auth: AuthContext = Depends(require_role("owner")),
    db: Session = Depends(get_db),
) -> dict:
    events = audit.recent(db, auth.org_id, limit=limit)
    if action:
        events = [event for event in events if event.action.startswith(action)]
    return {"events": [audit_event(event) for event in events]}


@router.get("/exports")
def list_exports(
    limit: int = Query(default=25, ge=1, le=100),
    auth: AuthContext = Depends(require_role("viewer")),
    db: Session = Depends(get_db),
) -> dict:
    rows = db.scalars(
        select(ReportExport)
        .where(ReportExport.org_id == auth.org_id)
        .order_by(ReportExport.id.desc())
        .limit(limit)
    ).all()
    return {
        "exports": [
            {
                "id": row.id,
                "kind": row.kind,
                "run_id": row.run_id,
                "filename": row.filename,
                "content_type": row.content_type,
                "byte_size": row.byte_size,
                "status": row.status,
                "created_at": iso(row.created_at),
            }
            for row in rows
        ]
    }
