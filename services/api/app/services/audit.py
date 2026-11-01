"""Append-only audit log for data, job and planning actions."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..models import AuditEvent, utcnow
from ..observability import get_request_id

logger = logging.getLogger("forecastops.audit")


def record(
    db: Session,
    *,
    org_id: int,
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    actor_user_id: int | None = None,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        org_id=org_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        payload=payload or {},
        request_id=request_id or get_request_id(),
        created_at=utcnow(),
    )
    db.add(event)
    logger.info(
        "audit %s %s#%s",
        action,
        entity_type,
        entity_id,
        extra={"context": {"action": action, "entity": entity_type, "entity_id": str(entity_id)}},
    )
    return event


def recent(db: Session, org_id: int, limit: int = 50) -> list[AuditEvent]:
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.org_id == org_id)
            .order_by(desc(AuditEvent.created_at), desc(AuditEvent.id))
            .limit(limit)
        )
    )
