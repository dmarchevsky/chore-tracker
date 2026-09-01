"""Ledger, balance and payout payloads (spec §4.3, §9, §10)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class LedgerEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    child_id: uuid.UUID
    occurrence_id: uuid.UUID | None
    kind: str
    amount_cents: int
    currency: str
    reason: str
    created_by: str
    reversed_by_entry_id: uuid.UUID | None
    created_at: datetime

    # Which chore the money was for, resolved from the occurrence (spec §4.3). "chore missed"
    # on its own tells a parent nothing about *which* chore, and the statement is where they
    # notice a wrong charge. NULL for entries that aren't tied to an occurrence — payouts,
    # hand-entered adjustments.
    chore_title: str | None = None
    occurrence_due_at: datetime | None = None


class BalanceOut(BaseModel):
    child_id: uuid.UUID
    balance_cents: int
    currency: str = "USD"


class PayoutCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    child_id: uuid.UUID
    amount_cents: int = Field(gt=0, description="positive; stored as a negative payout entry")
    method: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=1000)
    covers_through: date | None = None


class PayoutOut(LedgerEntryOut):
    method: str | None = None
    note: str | None = None
