"""Phase 4 acceptance: the LLM verification loop end to end (spec §14 Phase 4)."""

from __future__ import annotations

import io
import json
import random
from datetime import UTC, date, datetime, time

import httpx
import pytest
import respx
from PIL import Image
from sqlalchemy import func, select
from tests.helpers import sign_in

from app.models import (
    Chore,
    ChoreOccurrence,
    JobState,
    LedgerEntry,
    NotificationLog,
    OccurrenceStatus,
    Submission,
    SubmissionMedia,
    Verification,
    VerificationJob,
)
from app.models.verification import Verdict
from app.services.ledger import balance_cents
from app.worker import verify

pytestmark = pytest.mark.asyncio

LLM_URL = "http://llm-vision:8081/v1/chat/completions"


def _textured_jpeg(seed: int, w: int = 800, h: int = 600) -> bytes:
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for by in range(0, h, 25):
        for bx in range(0, w, 25):
            c = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            for y in range(by, min(by + 25, h)):
                for x in range(bx, min(bx + 25, w)):
                    px[x, y] = c
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _completion(payload: dict | str, finish_reason: str = "stop") -> httpx.Response:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}, "finish_reason": finish_reason}]},
    )


def _model_reply(checks: list[tuple[int, str, float]], overall=0.92, iq="none") -> dict:
    return {
        "checks": [{"id": i, "answer": a, "confidence": c, "evidence": ""} for i, a, c in checks],
        "overall_confidence": overall,
        "child_message": "message for the kid",
        "image_quality_issue": iq,
    }


async def _mk_occ(
    db,
    household,
    child,
    *,
    mode="llm_auto",
    reward=200,
    penalty=0,
    checklist=({"id": 1, "text": "Is the sink empty?", "required": True},),
) -> ChoreOccurrence:
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=child.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        photo_count=1,
        photo_prompts=["sink"],
        verification_mode=mode,
        verification_checklist=list(checklist) if checklist else None,
        reward_cents=reward,
        penalty_cents=penalty,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child.id,
        window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.open,
        reward_cents=reward,
        penalty_cents=penalty,
    )
    db.add(occ)
    await db.flush()
    return occ


async def _kid_submit(client, occ_id, *, seed=1):
    login = await sign_in(client, "alice@example.com")
    return await client.post(
        f"/api/v1/occurrences/{occ_id}/submissions",
        files=[("files", ("sink.jpg", _textured_jpeg(seed), "image/jpeg"))],
        data={"source": "camera"},
        headers={"X-CSRF-Token": login.json()["csrf_token"]},
    )


async def _make_media_look_real(db, occ_id) -> None:
    """Give the synthetic upload plausible camera EXIF so anti-cheat stays quiet."""
    rows = (
        (
            await db.execute(
                select(SubmissionMedia)
                .join(Submission, Submission.id == SubmissionMedia.submission_id)
                .where(Submission.occurrence_id == occ_id)
            )
        )
        .scalars()
        .all()
    )
    for m in rows:
        m.exif = {"Make": "TestCam", "Model": "T1"}
    subs = (
        (await db.execute(select(Submission).where(Submission.occurrence_id == occ_id)))
        .scalars()
        .all()
    )
    for s in subs:
        s.flags = []
    await db.commit()


async def _ledger_count(db, occ_id) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(LedgerEntry).where(LedgerEntry.occurrence_id == occ_id)
        )
    ).scalar_one()


@respx.mock
async def test_llm_auto_pass_credits_exactly_once(client, db_session, household, child_user):
    respx.post(LLM_URL).mock(return_value=_completion(_model_reply([(1, "yes", 0.95)])))
    occ = await _mk_occ(db_session, household, child_user, reward=250)
    await db_session.commit()

    r = await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)
    assert r.status_code == 201
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.submitted  # queued for the worker

    processed = await verify.drain(db_session)
    assert processed == 1
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.verified_pass
    assert await balance_cents(db_session, child_user.id) == 250
    assert await _ledger_count(db_session, occ.id) == 1

    v = (
        await db_session.execute(select(Verification).where(Verification.occurrence_id == occ.id))
    ).scalar_one()
    assert v.kind == "llm" and v.verdict == "pass" and v.raw_response is not None


@respx.mock
async def test_llm_auto_fail_is_held_for_a_parent_not_charged(
    client, db_session, household, admin_user, child_user
):
    respx.post(LLM_URL).mock(return_value=_completion(_model_reply([(1, "no", 0.9)])))
    occ = await _mk_occ(db_session, household, child_user, reward=200, penalty=100)
    await db_session.commit()
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    # spec §6.3 rule 2: the model's fail is a recommendation; only a parent takes money
    assert occ.status == OccurrenceStatus.needs_review
    assert await balance_cents(db_session, child_user.id) == 0
    assert await _ledger_count(db_session, occ.id) == 0

    v = (
        await db_session.execute(select(Verification).where(Verification.occurrence_id == occ.id))
    ).scalar_one()
    assert v.verdict == Verdict.fail  # the model's call stays on record for the parent
    assert v.child_message == "A parent will take a look."
    kid = (
        await db_session.execute(
            select(NotificationLog).where(NotificationLog.user_id == child_user.id)
        )
    ).scalar_one()
    assert kid.kind == "verdict.needs_review" and kid.title != "Not quite yet"
    assert await _review_pings(db_session) == 1


@respx.mock
async def test_llm_down_routes_to_needs_review_with_no_ledger(
    client, db_session, household, child_user
):
    respx.post(LLM_URL).mock(return_value=httpx.Response(500))
    occ = await _mk_occ(db_session, household, child_user, reward=200)
    await db_session.commit()
    await _kid_submit(client, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.needs_review
    assert occ.verification_error and "error" in occ.verification_error.lower()
    assert await _ledger_count(db_session, occ.id) == 0
    job = (await db_session.execute(select(VerificationJob))).scalar_one()
    assert job.state == JobState.done  # a human handles it, not a job retry


@respx.mock
async def test_llm_error_keeps_the_payloads_for_the_review_screen(
    client, db_session, household, child_user
):
    """An error verification used to store only its message, so a bad run was diagnosable
    from the worker log or not at all."""
    respx.post(LLM_URL).mock(return_value=_completion("", finish_reason="length"))
    occ = await _mk_occ(db_session, household, child_user, reward=200)
    await db_session.commit()
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    v = (
        await db_session.execute(select(Verification).where(Verification.occurrence_id == occ.id))
    ).scalar_one()
    assert v.verdict == Verdict.error
    assert v.raw_request is not None and v.raw_response is not None
    assert "truncated at max_tokens" in v.reasoning
    assert occ.status == OccurrenceStatus.needs_review
    assert await _ledger_count(db_session, occ.id) == 0


@respx.mock
async def test_llm_assist_always_routes_to_review(client, db_session, household, child_user):
    respx.post(LLM_URL).mock(return_value=_completion(_model_reply([(1, "yes", 0.99)])))
    occ = await _mk_occ(db_session, household, child_user, mode="llm_assist", reward=200)
    await db_session.commit()
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.needs_review
    assert await _ledger_count(db_session, occ.id) == 0


async def _review_pings(db) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(NotificationLog)
            .where(NotificationLog.kind == "admin.needs_review")
        )
        or 0
    )


@respx.mock
async def test_no_review_ping_while_the_model_still_has_it(
    client, db_session, household, admin_user, child_user
):
    """ "A chore needs your review" is a lie until a human is actually wanted.

    Submitting to an LLM-checked chore used to notify the parents immediately, while the
    status was SUBMITTED — "Checking…", the model's turn. Under llm_assist that also meant
    two pings for one submission: this one, then the real one after the model ran.
    """
    respx.post(LLM_URL).mock(return_value=_completion(_model_reply([(1, "yes", 0.99)])))
    occ = await _mk_occ(db_session, household, child_user, mode="llm_auto", reward=200)
    await db_session.commit()
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.submitted
    assert await _review_pings(db_session) == 0

    # The model passed it on its own — a human is never wanted, so none is ever asked.
    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.verified_pass
    assert await _review_pings(db_session) == 0


@respx.mock
async def test_the_review_ping_arrives_when_a_human_is_really_needed(
    client, db_session, household, admin_user, child_user
):
    """The other half: llm_assist hands every submission to a parent, and that is exactly
    when the ping should land — once, after the model has had its look (spec §4.1)."""
    respx.post(LLM_URL).mock(return_value=_completion(_model_reply([(1, "yes", 0.99)])))
    occ = await _mk_occ(db_session, household, child_user, mode="llm_assist", reward=200)
    await db_session.commit()
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)
    assert await _review_pings(db_session) == 0

    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.needs_review
    assert await _review_pings(db_session) == 1


@respx.mock
async def test_a_model_error_still_asks_for_a_human(
    client, db_session, household, admin_user, child_user
):
    """Fail-open (spec §6.3): if the model cannot answer, the parent must hear about it —
    otherwise dropping the submit-time ping would leave the chore silently stuck."""
    respx.post(LLM_URL).mock(side_effect=httpx.ConnectError("no route to llm"))
    occ = await _mk_occ(db_session, household, child_user, mode="llm_auto", reward=200)
    await db_session.commit()
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.needs_review
    assert await _review_pings(db_session) == 1


@respx.mock
async def test_image_quality_issue_reopens_occurrence(client, db_session, household, child_user):
    respx.post(LLM_URL).mock(
        return_value=_completion(_model_reply([(1, "unclear", 0.4)], iq="too_dark"))
    )
    occ = await _mk_occ(db_session, household, child_user, reward=200)
    await db_session.commit()
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.open
    assert await _ledger_count(db_session, occ.id) == 0


@respx.mock
async def test_duplicate_photo_is_flagged_and_reviewed(client, db_session, household, child_user):
    respx.post(LLM_URL).mock(return_value=_completion(_model_reply([(1, "yes", 0.99)])))
    first = await _mk_occ(db_session, household, child_user, reward=200)
    second = await _mk_occ(db_session, household, child_user, reward=200)
    await db_session.commit()

    await _kid_submit(client, first.id, seed=7)
    await _kid_submit(client, second.id, seed=7)  # identical image
    await verify.drain(db_session)

    await db_session.refresh(second)
    assert second.status == OccurrenceStatus.needs_review
    sub = (
        await db_session.execute(select(Submission).where(Submission.occurrence_id == second.id))
    ).scalar_one()
    assert "DUPLICATE_SUSPECTED" in sub.flags

    # The flag holds it for a human, but the model still ran: a parent deciding a flagged
    # submission needs its read of the photo, not just the flag.
    v = (
        await db_session.execute(
            select(Verification).where(Verification.occurrence_id == second.id)
        )
    ).scalar_one()
    assert v.kind == "llm" and v.verdict == Verdict.needs_review
    assert "DUPLICATE_SUSPECTED" in v.reasoning


@respx.mock
async def test_sparse_checklist_ids_still_decide_the_verdict(
    client, db_session, household, child_user
):
    """A parent deleting a middle row leaves ids like [1, 3]. The prompt used to renumber
    them 1..N, so the model answered under ids derive_verdict never looked at."""
    route = respx.post(LLM_URL).mock(
        return_value=_completion(_model_reply([(1, "yes", 0.99), (3, "no", 0.99)]))
    )
    occ = await _mk_occ(
        db_session,
        household,
        child_user,
        reward=200,
        penalty=100,
        checklist=[
            {"id": 1, "text": "Is the sink empty?", "required": True},
            {"id": 3, "text": "Is the counter clear?", "required": True},
        ],
    )
    await db_session.commit()
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)

    sent = json.loads(route.calls[0].request.content)["messages"][1]["content"][0]["text"]
    assert "1. Is the sink empty?" in sent
    assert "3. Is the counter clear?" in sent
    # The required "no" on id 3 is what fails it — the check was not silently dropped.
    v = (
        await db_session.execute(select(Verification).where(Verification.occurrence_id == occ.id))
    ).scalar_one()
    assert v.verdict == Verdict.fail
    assert occ.status == OccurrenceStatus.needs_review


# --- decider backend (spec §7.2 "Decider backend") ---------------------------------------

DECIDER_BASE = "http://decider.test/v1"
DECIDER_URL = f"{DECIDER_BASE}/systemone"


async def _use_decider(db) -> None:
    from app.services.llm_config import ensure_settings_row

    row = await ensure_settings_row(db)
    row.verifier_backend = "decider"
    row.decider_base_url = DECIDER_BASE
    await db.commit()


def _decider_reply(answers: dict[int, tuple[str, float]]) -> httpx.Response:
    def choice(c: str, p: float, opts: list[str]) -> dict:
        return {
            "type": "choice",
            "choice": c,
            "probabilities": {o: (p if o == c else (1 - p) / (len(opts) - 1)) for o in opts},
            "confidence": p,
        }

    out = {f"c{i}": choice(a, p, ["yes", "no", "unclear"]) for i, (a, p) in answers.items()}
    out["image_quality"] = choice(
        "none", 0.95, ["none", "too_dark", "too_blurry", "wrong_subject", "too_close", "too_far"]
    )
    return httpx.Response(200, json={"model": "d3-nano", "answers": out})


async def _only_verification(db, occ_id) -> Verification:
    return (
        await db.execute(select(Verification).where(Verification.occurrence_id == occ_id))
    ).scalar_one()


@respx.mock
async def test_decider_auto_pass_credits_and_names_its_model(
    client, db_session, household, child_user
):
    respx.post(DECIDER_URL).mock(return_value=_decider_reply({1: ("yes", 0.97)}))
    llm = respx.post(LLM_URL).mock(return_value=httpx.Response(500))
    occ = await _mk_occ(db_session, household, child_user, reward=250)
    await _use_decider(db_session)
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.verified_pass
    assert await balance_cents(db_session, child_user.id) == 250
    assert not llm.called
    v = await _only_verification(db_session, occ.id)
    assert v.model_name == "d3-nano"
    assert v.child_message  # the decider writes none; the worker supplies one
    assert v.raw_request["backend"] == "decider"


@respx.mock
async def test_decider_expect_no_end_to_end(client, db_session, household, child_user):
    respx.post(DECIDER_URL).mock(return_value=_decider_reply({1: ("no", 0.96)}))
    occ = await _mk_occ(
        db_session,
        household,
        child_user,
        reward=150,
        checklist=({"id": 1, "text": "Are there dishes in the basin?", "expect": "no"},),
    )
    await _use_decider(db_session)
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.verified_pass


@respx.mock
async def test_decider_failure_falls_back_to_llm(client, db_session, household, child_user):
    respx.post(DECIDER_URL).mock(return_value=httpx.Response(500))
    llm = respx.post(LLM_URL).mock(return_value=_completion(_model_reply([(1, "yes", 0.95)])))
    occ = await _mk_occ(db_session, household, child_user, reward=200)
    await _use_decider(db_session)
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert llm.called
    assert occ.status == OccurrenceStatus.verified_pass
    v = await _only_verification(db_session, occ.id)
    assert v.reasoning.startswith("decider failed (")
    assert "scored by LLM" in v.reasoning
    assert v.model_name != "d3-nano"


@respx.mock
async def test_decider_and_llm_both_down_fail_open(client, db_session, household, child_user):
    respx.post(DECIDER_URL).mock(side_effect=httpx.ConnectError("refused"))
    respx.post(LLM_URL).mock(return_value=httpx.Response(500))
    occ = await _mk_occ(db_session, household, child_user, reward=200)
    await _use_decider(db_session)
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    await db_session.refresh(occ)
    assert occ.status == OccurrenceStatus.needs_review
    assert await _ledger_count(db_session, occ.id) == 0
    assert occ.verification_error.startswith("decider failed (")
    assert "vision endpoint error" in occ.verification_error
    v = await _only_verification(db_session, occ.id)
    assert v.verdict == Verdict.error


@respx.mock
async def test_llm_backend_never_calls_the_decider(client, db_session, household, child_user):
    from app.services.llm_config import ensure_settings_row

    decider = respx.post(DECIDER_URL).mock(return_value=_decider_reply({1: ("yes", 0.99)}))
    respx.post(LLM_URL).mock(return_value=_completion(_model_reply([(1, "yes", 0.95)])))
    occ = await _mk_occ(db_session, household, child_user)
    row = await ensure_settings_row(db_session)
    row.decider_base_url = DECIDER_BASE  # configured, but not chosen
    await db_session.commit()
    await _kid_submit(client, occ.id)
    await _make_media_look_real(db_session, occ.id)

    await verify.drain(db_session)
    assert not decider.called
