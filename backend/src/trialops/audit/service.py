"""Append and query bounded, non-secret audit metadata."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trialops.reviews.models import AuditEventRecord

LOCAL_OPERATOR = "local-operator"
MAX_AUDIT_RESULTS = 100


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    created_at: datetime
    actor_id: str
    action: str
    entity_type: str
    entity_id: UUID
    details: dict[str, Any]


def append_audit_event(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: UUID,
    details: dict[str, Any] | None = None,
    actor_id: str = LOCAL_OPERATOR,
) -> UUID:
    """Stage an event inside the caller's transaction; never commit separately here."""
    event_id = uuid4()
    session.add(
        AuditEventRecord(
            id=event_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )
    return event_id


async def list_audit_events(
    session: AsyncSession, entity_id: UUID, *, limit: int = MAX_AUDIT_RESULTS
) -> tuple[AuditEvent, ...]:
    """Return the most recent events for one entity, never an unbounded dump."""
    records = (
        await session.scalars(
            select(AuditEventRecord)
            .where(AuditEventRecord.entity_id == entity_id)
            .order_by(AuditEventRecord.created_at.desc(), AuditEventRecord.id.desc())
            .limit(min(limit, MAX_AUDIT_RESULTS))
        )
    ).all()
    return tuple(AuditEvent.model_validate(record, from_attributes=True) for record in records)
