"""Audit — one run of the security & reliability audit against an agent.

This is the first-class record behind the unified flow: you "run" an agent and get
back an Audit (36 probes, Fireworks judge ensemble, findings, Trust/Potential score).
The full report is stored as JSON in `report`; aggregate scores are lifted out for
listing. Mirrors the Evaluation lifecycle (pending → running → completed/failed).
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import GUID, Base, JSONType, TimestampMixin, UUIDMixin


class AuditStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Audit(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "audits"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False, default="Audited agent")
    agent_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[AuditStatus] = mapped_column(
        SAEnum(AuditStatus, name="audit_status"),
        default=AuditStatus.PENDING,
        nullable=False,
        index=True,
    )
    trust_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    potential_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The full audit report payload (findings, judges, categories, standards, …).
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
