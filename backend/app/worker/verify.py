"""Verification worker: run the §7.1 pipeline for one queued job.

1. build the checklist prompt — the anti-cheat scan already ran at
   ingest, for every verification mode, and its flags are on the submission
2. call the vision model (with repair retry)
3. derive verdict + apply confidence banding — any anti-cheat flag forces NEEDS_REVIEW
4. write the Verification row, transition the occurrence, ledger only on a terminal
   auto pass/fail; llm_assist always routes to NEEDS_REVIEW
5. (Phase 5) push notification

Fail-open: any LLMError leaves the occurrence in NEEDS_REVIEW with verification_error and
writes NO ledger entry — the kid never loses money because inference broke (spec §6.3).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chore,
    ChoreOccurrence,
    OccurrenceStatus,
    Submission,
    SubmissionMedia,
    VerificationJob,
)
from app.models.chore import VerificationMode
from app.models.verification import Verdict, Verification
from app.services import ledger, notifications
from app.services.llm_config import get_llm_config
from app.services.media import read_media
from app.services.verification import build_task_prompt, derive_verdict, run_vision
from app.services.verification.llm import LLMError
from app.worker import queue

log = logging.getLogger("chorekeeper.worker.verify")

_OUTCOME_TO_VERDICT = {
    "pass": Verdict.pass_,
    "fail": Verdict.fail,
    "needs_review": Verdict.needs_review,
    "retake": Verdict.needs_review,
}


def _checklist(chore: Chore) -> tuple[list[tuple[int, str]], set[int]]:
    """``(id, question)`` pairs plus the ids that must pass. The ids travel all the way to
    the model and back, so a checklist with gaps (a parent deleted a row) still lines up."""
    items = chore.verification_checklist or []
    if not items and chore.verification_rule:
        items = [{"id": 1, "text": chore.verification_rule, "required": True}]
    checks = [(it["id"], it["text"]) for it in items]
    required = {it["id"] for it in items if it.get("required", True)}
    return checks, required


async def process_job(db: AsyncSession, job: VerificationJob) -> None:
    sub = await db.get(Submission, job.submission_id)
    occ = await db.get(ChoreOccurrence, job.occurrence_id)
    chore = await db.get(Chore, occ.chore_id) if occ else None
    if sub is None or occ is None or chore is None:
        await queue.complete(db, job)
        return
    await db.refresh(occ)  # act on the occurrence's committed state, not a cached copy

    # A human or another path may have already resolved it — don't clobber that.
    if occ.status not in (OccurrenceStatus.submitted, OccurrenceStatus.needs_review):
        await queue.complete(db, job)
        return

    mode = VerificationMode(chore.verification_mode)
    media_rows = list(
        (
            await db.execute(
                select(SubmissionMedia)
                .where(SubmissionMedia.submission_id == sub.id)
                .order_by(SubmissionMedia.idx)
            )
        )
        .scalars()
        .all()
    )

    checks, required_ids = _checklist(chore)
    prompt = build_task_prompt(
        chore_title=chore.title,
        photo_labels=[m.prompt_label or "" for m in media_rows],
        checks=checks,
    )

    cfg = await get_llm_config(db)
    try:
        images = [read_media(m.storage_path) for m in media_rows]
        response, raw_req, raw_resp = await run_vision(
            task_prompt=prompt, images=images, config=cfg
        )
    except LLMError as exc:
        v = _write_verification(
            db,
            occ,
            sub,
            Verdict.error,
            reasoning=str(exc),
            model_name=cfg.model,
        )
        occ.status = OccurrenceStatus.needs_review
        occ.verification_error = str(exc)[:200]
        await queue.complete(db, job)  # a human handles it; not a job-level retry
        await notifications.notify_verdict(db, occ, v)
        await notifications.notify_needs_review(db, occ)
        log.warning("verify job %s: LLM error -> NEEDS_REVIEW: %s", job.id, exc)
        return

    result = derive_verdict(
        response,
        required_ids=required_ids or None,
        auto_pass_threshold=float(chore.auto_pass_threshold),
        auto_fail_threshold=float(chore.auto_fail_threshold),
        flags=list(sub.flags),
    )

    v = _write_verification(
        db,
        occ,
        sub,
        _OUTCOME_TO_VERDICT[result.outcome],
        confidence=result.confidence,
        reasoning=result.reasoning,
        child_message=result.child_message,
        checks=result.checks,
        image_quality_issue=result.image_quality_issue,
        model_name=cfg.model,
        raw_request=raw_req,
        raw_response=raw_resp,
    )
    await _apply_outcome(db, occ, mode, result.outcome)
    await queue.complete(db, job)
    await notifications.notify_verdict(db, occ, v)
    if occ.status == OccurrenceStatus.needs_review:
        await notifications.notify_needs_review(db, occ)
    log.info("verify job %s -> %s (conf %.2f)", job.id, result.outcome, result.confidence)


async def _apply_outcome(
    db: AsyncSession, occ: ChoreOccurrence, mode: VerificationMode, outcome: str
) -> None:
    if outcome == "retake":
        occ.status = OccurrenceStatus.open  # kid retakes; no money (spec §7.3)
        return
    if mode is VerificationMode.llm_assist:
        occ.status = OccurrenceStatus.needs_review  # parent confirms all (spec §4.1)
        return
    # llm_auto
    if outcome == "pass":
        occ.status = OccurrenceStatus.verified_pass
        await ledger.credit_earning(db, occurrence=occ, reason="auto-verified pass")
    elif outcome == "fail":
        occ.status = OccurrenceStatus.verified_fail
        await ledger.debit_penalty(db, occurrence=occ, reason="auto-verified fail")
    else:
        occ.status = OccurrenceStatus.needs_review


def _write_verification(
    db: AsyncSession,
    occ: ChoreOccurrence,
    sub: Submission,
    verdict: Verdict,
    *,
    confidence: float | None = None,
    reasoning: str = "",
    child_message: str | None = None,
    checks: list[dict] | None = None,
    image_quality_issue: str | None = None,
    model_name: str | None = None,
    raw_request: dict | None = None,
    raw_response: dict | None = None,
) -> Verification:
    v = Verification(
        occurrence_id=occ.id,
        submission_id=sub.id,
        kind="llm",
        verdict=verdict,
        confidence=confidence,
        reasoning=reasoning,
        child_message=child_message,
        checks=checks,
        image_quality_issue=None if image_quality_issue in (None, "none") else image_quality_issue,
        model_name=model_name,
        raw_request=raw_request,
        raw_response=raw_response,
        created_by="system",
    )
    db.add(v)
    return v


async def drain(db: AsyncSession, *, limit: int = 20) -> int:
    """Process queued jobs until the queue is empty or ``limit`` is hit."""
    done = 0
    for _ in range(limit):
        job = await queue.claim_one(db)
        if job is None:
            break
        try:
            await process_job(db, job)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            job = await db.get(VerificationJob, job.id)
            if job is not None:
                await queue.fail(db, job, repr(exc))
                await db.commit()
            log.exception("verify job crashed")
        done += 1
    return done
