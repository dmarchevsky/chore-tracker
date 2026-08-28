"""Submission intake + routing + admin decisions (spec §3, §4.2, §4.4, §7).

Phase 3 covers the ``manual`` / ``auto_accept`` paths end to end. ``llm_auto`` / ``llm_assist``
route to SUBMITTED here and the Phase 4 worker takes over without changing this code
(spec §7.2). Anti-cheat flags force NEEDS_REVIEW, never an auto-fail (spec §6.1).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chore,
    ChoreOccurrence,
    LedgerEntry,
    LedgerKind,
    OccurrenceStatus,
    Submission,
    SubmissionKind,
    SubmissionMedia,
    SubmissionSource,
    User,
)
from app.models.chore import ProofType, VerificationMode
from app.models.verification import Verdict, Verification
from app.services import audit, ledger
from app.services.geo import evaluate_checkin
from app.services.media import ingest_photo

_LLM_MODES = {VerificationMode.llm_auto, VerificationMode.llm_assist}


class SubmissionError(ValueError):
    """Bad proof payload for the occurrence's proof_type / state."""


async def ingest_submission(
    db: AsyncSession,
    *,
    occurrence: ChoreOccurrence,
    chore: Chore,
    submitter: User,
    files: list[tuple[str, bytes]],
    note: str | None,
    geo: dict[str, Any] | None,
    source: str,
    client_meta: dict[str, Any] | None,
) -> Submission:
    proof = ProofType(chore.proof_type)
    src = SubmissionSource(source)
    flags: list[str] = []

    if src is SubmissionSource.gallery and not chore.allow_gallery_upload:
        raise SubmissionError("gallery upload is not allowed for this chore")
    if src is SubmissionSource.gallery:
        flags.append("GALLERY_UPLOAD")  # forced to review (spec §6.1)

    wants_photo = proof in (ProofType.photo, ProofType.photo_location)
    wants_geo = proof in (ProofType.location, ProofType.photo_location)
    kind = (
        SubmissionKind.photo
        if wants_photo
        else SubmissionKind.location
        if wants_geo
        else SubmissionKind.acknowledgement
    )

    if wants_photo and not files:
        raise SubmissionError("this chore needs at least one photo")
    if wants_photo and len(files) > max(chore.photo_count, 1):
        raise SubmissionError(f"expected at most {chore.photo_count} photo(s)")
    if wants_geo and not geo:
        raise SubmissionError("this chore needs a location check-in")

    sub = Submission(
        occurrence_id=occurrence.id,
        submitter_id=submitter.id,
        kind=kind,
        source=src,
        note=note,
        client_meta=client_meta,
        flags=flags,
    )
    db.add(sub)
    await db.flush()

    if wants_photo:
        prompts = chore.photo_prompts or []
        for idx, (_name, blob) in enumerate(files):
            res = ingest_photo(blob, household_id=str(chore.household_id))
            db.add(
                SubmissionMedia(
                    submission_id=sub.id,
                    idx=idx,
                    prompt_label=prompts[idx] if idx < len(prompts) else None,
                    sha256=res.sha256,
                    phash=res.phash,
                    width=res.width,
                    height=res.height,
                    bytes=res.bytes,
                    storage_path=res.storage_path,
                    exif=res.exif or None,
                )
            )

    if wants_geo and geo:
        fence = chore.geofence or {}
        chk = evaluate_checkin(
            lat=geo["lat"],
            lon=geo["lon"],
            accuracy_m=geo["accuracy"],
            center_lat=fence.get("lat", 0.0),
            center_lon=fence.get("lon", 0.0),
            radius_m=fence.get("radius_m", 0),
        )
        sub.geo_lat = round(geo["lat"], 4)  # coarse, ~11m (spec §6.2)
        sub.geo_lon = round(geo["lon"], 4)
        sub.geo_accuracy_m = geo["accuracy"]
        sub.geo_distance_m = round(chk.distance_m, 1)
        sub.geo_within = chk.within
        if chk.low_accuracy:
            sub.flags = [*sub.flags, "LOW_ACCURACY"]

    await db.flush()
    return sub


async def route_submission(
    db: AsyncSession, *, occurrence: ChoreOccurrence, chore: Chore, submission: Submission
) -> None:
    """Transition the occurrence after a submission (spec §3 state machine)."""
    mode = VerificationMode(chore.verification_mode)

    if submission.flags:  # any anti-cheat / quality flag -> human looks (spec §6.1)
        occurrence.status = OccurrenceStatus.needs_review
        return

    if mode is VerificationMode.auto_accept:
        if submission.kind is SubmissionKind.location and submission.geo_within is False:
            occurrence.status = OccurrenceStatus.needs_review
            return
        await _record_verification(
            db, occurrence, submission, Verdict.pass_, "auto-accepted", by="system"
        )
        occurrence.status = OccurrenceStatus.verified_pass
        await ledger.credit_earning(db, occurrence=occurrence, reason="auto-accepted")
        return

    # manual + (phase 3) llm_* all wait for a human; Phase 4 replaces this for llm_*.
    occurrence.status = OccurrenceStatus.submitted
    if mode in _LLM_MODES:
        occurrence.status = OccurrenceStatus.submitted  # TODO(phase4): enqueue LLM job


async def apply_decision(
    db: AsyncSession,
    *,
    occurrence: ChoreOccurrence,
    admin: User,
    action: str,
    reason: str,
    amount_override_cents: int | None = None,
) -> None:
    if occurrence.settlement_locked_at is not None:
        raise SubmissionError("occurrence is settlement-locked and cannot be changed")

    before = occurrence.status
    existing = await _earn_entries(db, occurrence.id)

    if action == "approve":
        for e in existing:
            if e.kind is LedgerKind.penalty and e.reversed_by_entry_id is None:
                await ledger.reverse_entry(db, entry=e, actor=admin, reason=f"approved: {reason}")
        await ledger.credit_earning(
            db,
            occurrence=occurrence,
            actor=admin,
            amount_override_cents=amount_override_cents,
            reason=reason,
        )
        occurrence.status = OccurrenceStatus.approved
        verdict = Verdict.pass_
    elif action == "reject":
        for e in existing:
            if e.kind is LedgerKind.earning and e.reversed_by_entry_id is None:
                await ledger.reverse_entry(db, entry=e, actor=admin, reason=f"rejected: {reason}")
        await ledger.debit_penalty(db, occurrence=occurrence, actor=admin, reason=reason)
        occurrence.status = OccurrenceStatus.rejected
        verdict = Verdict.fail
    elif action == "excuse":
        for e in existing:
            if e.reversed_by_entry_id is None and e.kind in (
                LedgerKind.earning,
                LedgerKind.penalty,
            ):
                await ledger.reverse_entry(db, entry=e, actor=admin, reason=f"excused: {reason}")
        occurrence.status = OccurrenceStatus.excused
        verdict = Verdict.needs_review
    elif action == "redo":
        occurrence.status = OccurrenceStatus.open  # reopen the window (spec §4.2)
        verdict = Verdict.needs_review
    else:  # pragma: no cover - schema enum guards this
        raise SubmissionError(f"unknown action {action!r}")

    await _record_verification(db, occurrence, None, verdict, reason, by="user", actor=admin)
    await audit.record(
        db,
        actor=admin,
        action=f"occurrence.decision.{action}",
        entity_type="occurrence",
        entity_id=occurrence.id,
        before={"status": before},
        after={"status": occurrence.status, "amount_override_cents": amount_override_cents},
    )


async def _earn_entries(db: AsyncSession, occurrence_id) -> list[LedgerEntry]:
    return list(
        (await db.execute(select(LedgerEntry).where(LedgerEntry.occurrence_id == occurrence_id)))
        .scalars()
        .all()
    )


async def _record_verification(
    db: AsyncSession,
    occurrence: ChoreOccurrence,
    submission: Submission | None,
    verdict: Verdict,
    reasoning: str,
    *,
    by: str,
    actor: User | None = None,
) -> Verification:
    v = Verification(
        occurrence_id=occurrence.id,
        submission_id=submission.id if submission else None,
        kind="manual",  # Phase 4 adds kind="llm" for worker verdicts
        verdict=verdict,
        reasoning=reasoning,
        created_by=by,
        actor_user_id=actor.id if actor else None,
    )
    db.add(v)
    await db.flush()
    return v
