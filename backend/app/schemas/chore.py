"""Request/response models for chore definitions and occurrences (spec §4.1, §10)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.chore import AssignmentMode, ProofType, VerificationMode
from app.models.occurrence import OccurrenceStatus
from app.services.cadence import CadenceError, cadence_dates
from app.services.rotation import RotationPeriod

_PHOTO_PROOFS = {ProofType.photo, ProofType.photo_location}


class GeofenceSpec(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: int = Field(ge=1, le=5000)
    arrive_before: time | None = None


class ChecklistItem(BaseModel):
    id: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=300)
    required: bool = True


class ChoreBase(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = ""

    assignment_mode: AssignmentMode
    fixed_assignee_id: uuid.UUID | None = None
    assignee_ids: list[uuid.UUID] = Field(default_factory=list)
    rotation_period: RotationPeriod | None = None
    rotation_anchor_date: date | None = None

    cadence: str = Field(min_length=1, max_length=120)
    due_time: time
    window_open_offset_s: int = Field(default=-12 * 3600, le=0, ge=-14 * 24 * 3600)
    grace_period_s: int = Field(default=15 * 60, ge=0, le=24 * 3600)
    start_date: date
    end_date: date | None = None

    proof_type: ProofType
    photo_count: int = Field(default=1, ge=0, le=6)
    photo_prompts: list[str] = Field(default_factory=list)
    allow_gallery_upload: bool = False
    prompt_token_enabled: bool = False
    geofence: GeofenceSpec | None = None

    verification_mode: VerificationMode
    verification_rule: str | None = None
    verification_checklist: list[ChecklistItem] | None = None
    auto_pass_threshold: float = Field(default=0.85, ge=0, le=1)
    auto_fail_threshold: float = Field(default=0.35, ge=0, le=1)

    reward_cents: int = Field(default=0, ge=0)
    penalty_cents: int = Field(default=0, ge=0)
    late_multiplier: float = Field(default=1.0, ge=0, le=1)

    active: bool = True

    @model_validator(mode="after")
    def _check(self) -> ChoreBase:
        try:
            cadence_dates(self.cadence, self.start_date, self.start_date)
        except CadenceError as exc:
            raise ValueError(f"invalid cadence: {exc}") from exc

        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")

        if self.auto_fail_threshold > self.auto_pass_threshold:
            raise ValueError("auto_fail_threshold must be <= auto_pass_threshold")

        if self.assignment_mode == AssignmentMode.fixed and not self.fixed_assignee_id:
            raise ValueError("fixed assignment_mode requires fixed_assignee_id")
        if self.assignment_mode == AssignmentMode.rotating:
            if len(self.assignee_ids) < 2:
                raise ValueError("rotating assignment_mode needs >= 2 assignee_ids")
            if not self.rotation_period or not self.rotation_anchor_date:
                raise ValueError(
                    "rotating assignment_mode needs rotation_period and rotation_anchor_date"
                )
        if self.assignment_mode == AssignmentMode.all and not self.assignee_ids:
            raise ValueError("all assignment_mode needs assignee_ids")

        if self.proof_type in _PHOTO_PROOFS and self.photo_count < 1:
            raise ValueError(f"proof_type {self.proof_type} needs photo_count >= 1")
        if self.proof_type in {ProofType.location, ProofType.photo_location} and not self.geofence:
            raise ValueError(f"proof_type {self.proof_type} needs a geofence")
        return self


class ChoreCreate(ChoreBase):
    pass


class ChoreUpdate(BaseModel):
    """Partial update. Applied per ``?apply=forward|future_generated`` (spec §4.1, §10)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    cadence: str | None = Field(default=None, min_length=1, max_length=120)
    due_time: time | None = None
    window_open_offset_s: int | None = Field(default=None, le=0, ge=-14 * 24 * 3600)
    grace_period_s: int | None = Field(default=None, ge=0, le=24 * 3600)
    end_date: date | None = None
    photo_count: int | None = Field(default=None, ge=0, le=6)
    photo_prompts: list[str] | None = None
    allow_gallery_upload: bool | None = None
    prompt_token_enabled: bool | None = None
    verification_mode: VerificationMode | None = None
    verification_rule: str | None = None
    verification_checklist: list[ChecklistItem] | None = None
    auto_pass_threshold: float | None = Field(default=None, ge=0, le=1)
    auto_fail_threshold: float | None = Field(default=None, ge=0, le=1)
    reward_cents: int | None = Field(default=None, ge=0)
    penalty_cents: int | None = Field(default=None, ge=0)
    late_multiplier: float | None = Field(default=None, ge=0, le=1)
    active: bool | None = None


class ChoreOut(ChoreBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    household_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class OccurrenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chore_id: uuid.UUID
    assignee_id: uuid.UUID | None
    window_open_at: datetime
    due_at: datetime
    status: OccurrenceStatus
    was_late: bool
    settlement_locked_at: datetime | None
    reward_cents: int
    penalty_cents: int


class OccurrencePreviewItem(BaseModel):
    due_at: datetime
    window_open_at: datetime
    assignee_id: uuid.UUID | None


class AssigneeSwap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_id: uuid.UUID | None = None
