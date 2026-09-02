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
    # Set only by a manually applied penalty (spec §4.8). With occurrence_id NULL it is what
    # tells the UI this was a parent charging a rule, not a missed chore — the two share the
    # `penalty` kind but offer different affordances (excuse vs undo).
    chore_id: uuid.UUID | None = None
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


class PenaltyApplyRequest(BaseModel):
    """Body for ``POST /penalties`` — charge a kid against a penalty rule (spec §4.8)."""

    model_config = ConfigDict(extra="forbid")

    chore_id: uuid.UUID
    child_id: uuid.UUID
    tier_id: int = Field(ge=1)
    amount_override_cents: int | None = Field(
        default=None, gt=0, description="positive magnitude; the service applies the sign"
    )
    note: str | None = Field(default=None, max_length=500)


class PenaltyReverseRequest(BaseModel):
    """Body for ``POST /penalties/{entry_id}/reverse``.

    The reason is required and not optional flavour: it lands on the kid's statement as the
    line that undoes the charge, so "why" is the whole content of the row.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
