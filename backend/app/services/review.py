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
from app.services import anti_cheat, audit, ledger, notifications
from app.services.geo import GeoCheck, evaluate_checkin
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
        flags.append(anti_cheat.FLAG_GALLERY)  # forced to review (spec §6.1)

    wants_photo = proof in (ProofType.photo, ProofType.photo_location)
    wants_geo = proof in (ProofType.location, ProofType.photo_location)
    kind = (
        SubmissionKind.photo
        if wants_photo
        else SubmissionKind.location
        if wants_geo
        else SubmissionKind.acknowledgement
    )

    wanted = max(chore.photo_count, 1)
    if wants_photo and not files:
        raise SubmissionError(
            "this chore needs a photo" if wanted == 1 else f"this chore needs {wanted} photos"
        )
    # Exactly, not at most: photo_count is the number of angles the chore asks for, and a
    # short submission used to sail through the API and the offline replay queue while the
    # camera sheet refused to send one (spec §6.1 item 6).
    if wants_photo and len(files) != wanted:
        raise SubmissionError(f"this chore needs exactly {wanted} photo(s), got {len(files)}")
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
        sub.flags = [*sub.flags, *geo_flags(chk)]

    await db.flush()

    # Scan every photo submission, whatever the verification mode. This used to run only
    # in the LLM worker, so a `manual` or `auto_accept` chore got no duplicate detection at
    # all — and auto_accept paid out an instantly-recycled photo (spec §6.1 item 2).
    if wants_photo:
        found = await anti_cheat.scan_submission(db, sub)
        if found:
            sub.flags = sorted(set(sub.flags) | set(found))
            await db.flush()
    return sub


def geo_flags(chk: GeoCheck) -> list[str]:
    """Flags a check-in earns on its own. Shared with the webhook path (spec §6.2)."""
    flags = []
    if chk.low_accuracy:
        flags.append(anti_cheat.FLAG_LOW_ACCURACY)
    if not chk.within:
        # Was only enforced for `location` proof under auto_accept: a photo+location
        # submission has kind == photo, so an out-of-fence check-in slipped through every
        # mode. As a flag it routes uniformly (spec §6.1).
        flags.append(anti_cheat.FLAG_OUTSIDE_FENCE)
    return flags


async def route_submission(
    db: AsyncSession, *, occurrence: ChoreOccurrence, chore: Chore, submission: Submission
) -> None:
    """Transition the occurrence after a submission (spec §3 state machine)."""
    mode = VerificationMode(chore.verification_mode)

    if mode in _LLM_MODES:
        # Flagged or not, let the model look: derive_verdict routes any flag to review
        # regardless of what it says (spec §6.3 rule 2), and a parent reviewing a flag is
        # much better off seeing the model's read of the photo than the flag alone.
        occurrence.status = OccurrenceStatus.submitted
        await notifications.notify_needs_review(db, occurrence)
        from app.worker.queue import enqueue

        await enqueue(db, occurrence_id=occurrence.id, submission_id=submission.id)
        return

    if submission.flags:  # any anti-cheat / quality flag -> human looks (spec §6.1)
        occurrence.status = OccurrenceStatus.needs_review
        await notifications.notify_needs_review(db, occurrence)
        return

    if mode is VerificationMode.auto_accept:
        v = await _record_verification(
            db, occurrence, submission, Verdict.pass_, "auto-accepted", by="system"
        )
        occurrence.status = OccurrenceStatus.verified_pass
        await ledger.credit_earning(db, occurrence=occurrence, reason="auto-accepted")
        await notifications.notify_verdict(db, occurrence, v)
        return

    occurrence.status = OccurrenceStatus.submitted  # manual -> waits for a human
    await notifications.notify_needs_review(db, occurrence)


async def apply_decision(
    db: AsyncSession,
    *,
    occurrence: ChoreOccurrence,
    admin: User,
    action: str,
    reason: str,
    amount_override_cents: int | None = None,
    tier_id: int | None = None,
) -> None:
    if occurrence.settlement_locked_at is not None:
        raise SubmissionError("occurrence is settlement-locked and cannot be changed")

    before = occurrence.status
    existing = await _earn_entries(db, occurrence.id)

    # A tiered chore is graded by picking one condition, not by approve/reject. Prefer the
    # occurrence's snapshot so editing the chore never re-prices a decided occurrence
    # (spec §3); fall back to the definition for rows generated before tiers existed.
    tiers = occurrence.outcome_tiers
    if tiers is None:
        chore = await db.get(Chore, occurrence.chore_id)
        tiers = chore.outcome_tiers if chore else None
    if tiers and action in ("approve", "reject"):
        raise SubmissionError(
            "this chore is decided by picking an outcome tier, not approve/reject"
        )

    # `kind` is a plain String column, so an entry loaded in a later request carries a str,
    # not the enum member — `is` silently matched nothing and a changed decision left the
    # original entry standing.
    if action == "approve":
        for e in existing:
            if e.kind == LedgerKind.penalty and e.reversed_by_entry_id is None:
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
            if e.kind == LedgerKind.earning and e.reversed_by_entry_id is None:
                await ledger.reverse_entry(db, entry=e, actor=admin, reason=f"rejected: {reason}")
        await ledger.debit_penalty(db, occurrence=occurrence, actor=admin, reason=reason)
        occurrence.status = OccurrenceStatus.rejected
        verdict = Verdict.fail
    elif action == "tier":
        if not tiers:
            raise SubmissionError("this chore has no outcome tiers")
        tier = next((t for t in tiers if t["id"] == tier_id), None)
        if tier is None:
            raise SubmissionError(f"tier {tier_id} is not one of this chore's outcomes")

        # A double-clicked tier button must not move money twice. This guard is stronger
        # than the ledger's (occurrence_id, kind) index, which only knows about the kind.
        if occurrence.outcome_tier_id == tier_id and occurrence.status == OccurrenceStatus.approved:
            return

        # Re-deciding: unwind whatever the previous tier posted, then post the new amount.
        for e in existing:
            if e.reversed_by_entry_id is None and e.kind in (
                LedgerKind.earning,
                LedgerKind.penalty,
            ):
                await ledger.reverse_entry(
                    db, entry=e, actor=admin, reason=f"outcome changed: {reason}"
                )
        await ledger.post_tier_outcome(
            db, occurrence=occurrence, tier=tier, actor=admin, reason=reason
        )
        occurrence.outcome_tier_id = tier_id
        occurrence.outcome_tier = tier
        # No new terminal status: APPROVED plus a recorded tier is the decision (spec §4.6).
        # The UI renders the tier's condition where it would otherwise say "Approved".
        occurrence.status = OccurrenceStatus.approved
        verdict = Verdict.fail if (tier.get("amount_cents") or 0) < 0 else Verdict.pass_
    elif action == "excuse":
        for e in existing:
            if e.reversed_by_entry_id is None and e.kind in (
                LedgerKind.earning,
                LedgerKind.penalty,
            ):
                await ledger.reverse_entry(db, entry=e, actor=admin, reason=f"excused: {reason}")
        # Clear any chosen tier: otherwise the idempotency guard above would treat a later
        # re-pick of that same tier as a no-op and the money would never be re-posted.
        occurrence.outcome_tier_id = None
        occurrence.outcome_tier = None
        occurrence.status = OccurrenceStatus.excused
        verdict = Verdict.needs_review
    elif action == "redo":
        occurrence.status = OccurrenceStatus.open  # reopen the window (spec §4.2)
        verdict = Verdict.needs_review
    else:  # pragma: no cover - schema enum guards this
        raise SubmissionError(f"unknown action {action!r}")

    # The reason is what the kid reads on the chore — a decision they can't see the
    # reasoning for is just a number moving (spec §6.3 rule 1).
    v = await _record_verification(
        db, occurrence, None, verdict, reason, by="user", actor=admin, child_message=reason
    )
    await audit.record(
        db,
        actor=admin,
        action=f"occurrence.decision.{action}",
        entity_type="occurrence",
        entity_id=occurrence.id,
        before={"status": before},
        after={
            "status": occurrence.status,
            "amount_override_cents": amount_override_cents,
            "tier_id": tier_id,
        },
    )
    if action == "redo":
        await notifications.notify_redo(db, occurrence, reason)
    else:
        await notifications.notify_verdict(db, occurrence, v)


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
    child_message: str | None = None,
) -> Verification:
    v = Verification(
        occurrence_id=occurrence.id,
        submission_id=submission.id if submission else None,
        kind="manual",  # Phase 4 adds kind="llm" for worker verdicts
        verdict=verdict,
        reasoning=reasoning,
        child_message=child_message,
        created_by=by,
        actor_user_id=actor.id if actor else None,
    )
    db.add(v)
    await db.flush()
    return v
