"""Submission, verification and decision payloads (spec §4.2, §4.4, §10)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GeoIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy: float = Field(ge=0, le=10000)
    captured_at: datetime | None = None


class SubmissionMediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    idx: int
    prompt_label: str | None
    sha256: str
    phash: str | None
    width: int
    height: int
    bytes: int
    mime: str
    exif: dict[str, Any] | None
    url: str | None = None  # signed, short-TTL — filled by the media router


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurrence_id: uuid.UUID
    submitter_id: uuid.UUID | None
    kind: str
    source: str
    note: str | None
    flags: list[str]
    geo_lat: float | None
    geo_lon: float | None
    geo_accuracy_m: float | None
    geo_distance_m: float | None
    geo_within: bool | None
    created_at: datetime
    media: list[SubmissionMediaOut]


class VerificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    occurrence_id: uuid.UUID
    submission_id: uuid.UUID | None
    kind: str
    verdict: str
    confidence: float | None
    reasoning: str | None
    child_message: str | None
    checks: list[dict[str, Any]] | None
    image_quality_issue: str | None
    model_name: str | None
    created_by: str
    created_at: datetime


class VerificationRawOut(VerificationOut):
    """Admin-only — the full model request/response (spec §10 GET /verifications/{id})."""

    raw_request: dict[str, Any] | None
    raw_response: dict[str, Any] | None


class DecisionAction(enum.StrEnum):
    approve = "approve"
    reject = "reject"
    excuse = "excuse"
    redo = "redo"
    tier = "tier"


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DecisionAction
    reason: str = Field(min_length=1, max_length=1000)
    amount_override_cents: int | None = Field(default=None, ge=0)
    tier_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _check(self) -> DecisionRequest:
        if self.action is DecisionAction.tier:
            if self.tier_id is None:
                raise ValueError("action=tier needs a tier_id")
            if self.amount_override_cents is not None:
                raise ValueError("action=tier takes its amount from the tier, not an override")
        elif self.tier_id is not None:
            raise ValueError(f"tier_id is only meaningful for action=tier, not {self.action}")
        return self


class DisputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1000)
