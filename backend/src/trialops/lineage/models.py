"""Persistence model for immutable on-demand reproduction comparisons."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from trialops.db.base import Base


class ReproductionRunRecord(Base):
    """One recorded rerun comparison; application code only inserts rows."""

    __tablename__ = "reproduction_run"
    __table_args__ = (
        CheckConstraint("status IN ('EXACT_MATCH', 'MISMATCH')", name="valid_status"),
        CheckConstraint("difference_count >= 0", name="nonnegative_difference_count"),
        CheckConstraint("stored_result_sha256 ~ '^[0-9a-f]{64}$'", name="stored_sha256"),
        CheckConstraint("reproduced_result_sha256 ~ '^[0-9a-f]{64}$'", name="reproduced_sha256"),
        CheckConstraint("jsonb_typeof(differences) = 'array'", name="differences_array"),
    )

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_plan.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(16))
    stored_result_sha256: Mapped[str] = mapped_column(String(64))
    reproduced_result_sha256: Mapped[str] = mapped_column(String(64))
    difference_count: Mapped[int] = mapped_column(Integer)
    differences: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    differences_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
