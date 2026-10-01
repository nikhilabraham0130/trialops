"""Read-only, entity-scoped audit history."""

from uuid import UUID

from fastapi import APIRouter, Query

from trialops.api.dependencies import DatabaseSession
from trialops.audit.service import AuditEvent, list_audit_events

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=tuple[AuditEvent, ...])
async def read_audit_events(
    entity_id: UUID,
    session: DatabaseSession,
    limit: int = Query(default=100, ge=1, le=100),
) -> tuple[AuditEvent, ...]:
    """Inspect up to one hundred recent business events for one saved entity."""
    return await list_audit_events(session, entity_id, limit=limit)
