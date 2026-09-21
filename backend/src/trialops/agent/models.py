"""Database model for server-controlled analysis plans."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trialops.agent.contracts import ApprovedToolName, PlanStatus
from trialops.db.base import Base


class AgentPlanRecord(Base):
    """Exact approved-tool plan retained for later confirmation and execution."""

    __tablename__ = "agent_plan"
    __table_args__ = (
        CheckConstraint("btrim(question) <> ''", name="nonempty_question"),
        CheckConstraint("btrim(purpose) <> ''", name="nonempty_purpose"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("dataset_version.id", ondelete="RESTRICT"),
        index=True,
    )
    question: Mapped[str] = mapped_column(String(2000))
    purpose: Mapped[str] = mapped_column(String(2000))
    status: Mapped[PlanStatus] = mapped_column(
        Enum(
            PlanStatus,
            name="agent_plan_status",
            native_enum=False,
            create_constraint=True,
            length=32,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        )
    )
    tool_name: Mapped[ApprovedToolName] = mapped_column(
        Enum(
            ApprovedToolName,
            name="approved_tool_name",
            native_enum=False,
            create_constraint=True,
            length=64,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        )
    )
    tool_arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
