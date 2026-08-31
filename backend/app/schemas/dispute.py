"""Dispute payloads (spec §4.2)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.dispute import DisputeStatus


class DisputeResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=1000)  # the kid reads this


class DisputeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurrence_id: uuid.UUID
    author_user_id: uuid.UUID | None
    message: str
    status: DisputeStatus
    status_at_filing: str | None
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime


class DisputeWithContext(DisputeOut):
    """Admin listing — enough to triage without a second round-trip per row."""

    chore_title: str | None = None
    author_name: str | None = None
    occurrence_status: str | None = None
    occurrence_due_at: datetime | None = None
