"""Database model for clinical studies."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from trialops.db.base import Base


class Study(Base):
    """A clinical study known to TrialOps."""

    __tablename__ = "study"
    __table_args__ = (UniqueConstraint("study_oid", name="uq_study_study_oid"),)

    id: Mapped[UUID] = mapped_column(
        default=uuid4,
        server_default=text("gen_random_uuid()"),
        primary_key=True,
    )
    study_oid: Mapped[str] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
