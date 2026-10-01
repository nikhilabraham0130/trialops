"""Audit events are bounded, entity-scoped, and omit raw query text."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from trialops.audit.service import append_audit_event, list_audit_events
from trialops.reviews.models import AuditEventRecord


def test_append_stages_business_event_without_committing() -> None:
    session = AsyncMock(spec=AsyncSession)
    entity_id = uuid4()
    event_id = append_audit_event(
        session,
        action="ANALYSIS_EXECUTED",
        entity_type="agent_plan",
        entity_id=entity_id,
        details={"tool_name": "calculate_alt_gt_3x_uln"},
    )
    record = session.add.call_args.args[0]
    assert isinstance(record, AuditEventRecord)
    assert record.id == event_id
    assert record.entity_id == entity_id
    assert record.actor_id == "local-operator"
    assert session.commit.await_count == 0


def test_audit_lookup_returns_bounded_typed_events() -> None:
    session = AsyncMock(spec=AsyncSession)
    entity_id = uuid4()
    record = AuditEventRecord(
        id=uuid4(),
        actor_id="local-operator",
        action="ANALYSIS_CREATED",
        entity_type="agent_plan",
        entity_id=entity_id,
        details={},
        created_at=datetime.now(UTC),
    )
    session.scalars.return_value = SimpleNamespace(all=lambda: [record])
    events = asyncio.run(list_audit_events(session, entity_id, limit=1000))
    assert len(events) == 1
    assert events[0].action == "ANALYSIS_CREATED"
    assert events[0].entity_id == entity_id
    assert "LIMIT 100" in str(
        session.scalars.call_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
