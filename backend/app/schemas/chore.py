"""Request/response models for chore definitions and occurrences (spec §4.1, §10)."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.chore import AssignmentMode, ProofType, VerificationMode
from app.models.occurrence import OccurrenceStatus
from app.services.cadence import CadenceError, cadence_dates, once_date
from app.services.rotation import RotationPeriod

_PHOTO_PROOFS = {ProofType.photo, ProofType.photo_location}
_LLM_MODES = {VerificationMode.llm_auto, VerificationMode.llm_assist}
_MAX_TIERS = 8


class GeofenceSpec(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_m: int = Field(ge=1, le=5000)
    arrive_before: time | None = None


class ChecklistItem(BaseModel):
    id: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=300)
    required: bool = True


class OutcomeKind(enum.StrEnum):
    money = "money"
    text = "text"


class OutcomeTier(BaseModel):
    """One condition -> outcome row of a graded chore (spec §4.6).

    ``amount_cents`` is **signed**, unlike ``reward_cents``/``penalty_cents`` which are
    unsigned magnitudes whose sign ledger.debit_penalty applies. One tier list carries both
    rewards and penalties, so the sign is the only thing that says which — and it is what
    routes the ledger kind. The admin form never asks a parent to type a minus sign; it
    offers a Reward/Penalty toggle and stores the sign itself.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    condition: str = Field(min_length=1, max_length=300)
    outcome_kind: OutcomeKind
    amount_cents: int | None = None
    text: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _shape(self) -> OutcomeTier:
        if self.outcome_kind is OutcomeKind.money:
            if not self.amount_cents:
                raise ValueError("a money tier needs a non-zero amount_cents")
            if self.text is not None:
                raise ValueError("a money tier must not carry outcome text")
        else:
            if not (self.text and self.text.strip()):
                raise ValueError("a text tier needs outcome text")
            if self.amount_cents is not None:
                raise ValueError("a text tier must not carry an amount")
        return self


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
    geofence: GeofenceSpec | None = None

    verification_mode: VerificationMode
    verification_rule: str | None = None
    verification_checklist: list[ChecklistItem] | None = None
    auto_pass_threshold: float = Field(default=0.85, ge=0, le=1)
    auto_fail_threshold: float = Field(default=0.35, ge=0, le=1)

    outcome_tiers: list[OutcomeTier] | None = None

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

        # A one-off carries its date in the cadence, so it can contradict the date bounds.
        # Both rules below are *static* on purpose: PATCH re-validates the whole merged
        # definition (api/v1/chores.py), so a rule referencing "today" would make a chore
        # un-editable the day after it fired — you could no longer fix its title.
        once = once_date(self.cadence)
        if once is not None:
            if once < self.start_date:
                raise ValueError(
                    f"once({once}) is before start_date {self.start_date}, so it can never fire"
                )
            if self.end_date and once > self.end_date:
                raise ValueError(
                    f"once({once}) is after end_date {self.end_date}, so it can never fire"
                )

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
        if self.photo_prompts and len(self.photo_prompts) != self.photo_count:
            # The kid's capture screen derives its slots from the labels, so a mismatch
            # shows slots whose photos ingest would then reject.
            raise ValueError(
                f"photo_prompts has {len(self.photo_prompts)} label(s) "
                f"but photo_count is {self.photo_count}"
            )
        if self.verification_mode in _LLM_MODES and self.proof_type not in _PHOTO_PROOFS:
            # There is no image to judge, and run_vision would happily send a text-only
            # message — under llm_auto that verdict moves money (spec §7.2).
            raise ValueError(
                f"verification_mode {self.verification_mode} needs a photo proof_type; "
                f"{self.proof_type} has no image for the model to look at"
            )
        if self.proof_type in {ProofType.location, ProofType.photo_location} and not self.geofence:
            raise ValueError(f"proof_type {self.proof_type} needs a geofence")

        # Tier rules are all gated on the chore actually having tiers, so every existing
        # definition keeps validating exactly as before (spec §4.6).
        if self.outcome_tiers:
            if len(self.outcome_tiers) > _MAX_TIERS:
                raise ValueError(f"at most {_MAX_TIERS} outcome tiers")
            if [t.id for t in self.outcome_tiers] != list(range(1, len(self.outcome_tiers) + 1)):
                # Same renumber-on-every-edit contract as verification_checklist, so
                # "tier 3" means the same thing in the audit log as on screen.
                raise ValueError("outcome_tiers ids must be 1..N in order")
            if self.verification_mode is not VerificationMode.manual:
                # An LLM cannot judge "all A grades", and under llm_auto its opinion would
                # move money. auto_accept terminally passes with no human in the loop, so
                # nobody would ever pick a tier and the chore would silently pay nothing.
                raise ValueError(
                    "a chore with outcome tiers must use verification_mode=manual — "
                    "a tier is chosen by a person"
                )
            if self.verification_rule or self.verification_checklist:
                raise ValueError(
                    "a tiered chore has no LLM step, so it cannot carry a "
                    "verification_rule or verification_checklist"
                )
            if self.reward_cents or self.penalty_cents or self.late_multiplier != 1.0:
                raise ValueError(
                    "a tiered chore's money comes from its tiers — set reward_cents and "
                    "penalty_cents to 0 and leave late_multiplier at 1.0"
                )
        return self


class ChoreCreate(ChoreBase):
    pass


class ChoreDuplicate(BaseModel):
    """Body for ``POST /chores/{id}/duplicate`` (spec §4.1: admin MUST be able to clone).

    Only the copy's title is settable; every other field is taken from the source.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=160)


class ChoreUpdate(BaseModel):
    """Partial update. Applied per ``?apply=forward|future_generated`` (spec §4.1, §10)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None

    # Reassignment (spec §4.1) — proof_type / start_date stay immutable (they would
    # invalidate existing occurrences and their proof/money history).
    assignment_mode: AssignmentMode | None = None
    fixed_assignee_id: uuid.UUID | None = None
    assignee_ids: list[uuid.UUID] | None = None
    rotation_period: RotationPeriod | None = None
    rotation_anchor_date: date | None = None

    cadence: str | None = Field(default=None, min_length=1, max_length=120)
    due_time: time | None = None
    window_open_offset_s: int | None = Field(default=None, le=0, ge=-14 * 24 * 3600)
    grace_period_s: int | None = Field(default=None, ge=0, le=24 * 3600)
    end_date: date | None = None
    photo_count: int | None = Field(default=None, ge=0, le=6)
    photo_prompts: list[str] | None = None
    allow_gallery_upload: bool | None = None
    geofence: GeofenceSpec | None = None
    verification_mode: VerificationMode | None = None
    verification_rule: str | None = None
    verification_checklist: list[ChecklistItem] | None = None
    auto_pass_threshold: float | None = Field(default=None, ge=0, le=1)
    auto_fail_threshold: float | None = Field(default=None, ge=0, le=1)
    outcome_tiers: list[OutcomeTier] | None = None
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
    outcome_tiers: list[OutcomeTier] | None = None
    outcome_tier_id: int | None = None
    outcome_tier: OutcomeTier | None = None
    verification_error: str | None = None


class OccurrencePreviewItem(BaseModel):
    due_at: datetime
    window_open_at: datetime
    assignee_id: uuid.UUID | None


class AssigneeSwap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_id: uuid.UUID | None = None
