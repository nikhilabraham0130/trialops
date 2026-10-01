"""Review and audit records retained with the exact analysis plan."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trialops.db.base import Base


class ReviewEventRecord(Base):
    __tablename__ = "review_event"
    __table_args__ = (
        CheckConstraint("btrim(actor_id) <> ''", name="nonempty_actor_id"),
        CheckConstraint(
            "action IN ('SUBMITTED', 'APPROVED', 'CHANGES_REQUESTED', 'REJECTED')",
            name="valid_action",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_plan.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(128))
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEventRecord(Base):
    __tablename__ = "audit_event"
    __table_args__ = (CheckConstraint("btrim(actor_id) <> ''", name="nonempty_actor_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[UUID] = mapped_column(index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
