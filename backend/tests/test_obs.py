"""Phase 6: structured JSON logging + the audit stream (spec §5)."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, time

import pytest

from app import obs
from app.models import Chore, ChoreOccurrence, OccurrenceStatus
from app.models.verification import Verdict, Verification
from app.services import audit
from app.services.ledger import credit_earning, reverse_entry


def test_json_formatter_emits_one_line_object():
    rec = logging.LogRecord(
        "chorekeeper.test", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    rec.event = "ledger.entry"
    rec.amount_cents = -250
    line = obs.JsonFormatter().format(rec)
    assert "\n" not in line
    parsed = json.loads(line)
    assert parsed["msg"] == "hello world"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "chorekeeper.test"
    assert parsed["event"] == "ledger.entry" and parsed["amount_cents"] == -250
    datetime.fromisoformat(parsed["ts"])  # parseable ISO-8601


def test_json_formatter_renders_exceptions():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    parsed = json.loads(obs.JsonFormatter().format(rec))
    assert "ValueError: boom" in parsed["exc"]


async def _occ(db, household, child, *, reward=200) -> ChoreOccurrence:
    chore = Chore(
        household_id=household.id,
        title="Kitchen",
        assignment_mode="fixed",
        fixed_assignee_id=child.id,
        cadence="daily",
        due_time=time(8, 0),
        start_date=date(2025, 1, 1),
        proof_type="photo",
        verification_mode="manual",
        reward_cents=reward,
    )
    db.add(chore)
    await db.flush()
    occ = ChoreOccurrence(
        household_id=household.id,
        chore_id=chore.id,
        assignee_id=child.id,
        window_open_at=datetime(2025, 1, 2, tzinfo=UTC),
        due_at=datetime(2025, 1, 2, 16, tzinfo=UTC),
        status=OccurrenceStatus.verified_pass,
        reward_cents=reward,
    )
    db.add(occ)
    await db.flush()
    return occ


def _events(caplog, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "event", None) == name]


async def test_ledger_insert_emits_an_audit_line(caplog, db_session, household, child_user):
    occ = await _occ(db_session, household, child_user)
    with caplog.at_level(logging.INFO, logger=obs.AUDIT_LOGGER):
        entry = await credit_earning(db_session, occurrence=occ, reason="chore approved")
        await db_session.flush()

    (rec,) = _events(caplog, "ledger.entry")
    assert rec.entry_id == str(entry.id)
    assert rec.amount_cents == 200
    assert rec.kind == "earning"
    assert rec.child_id == str(child_user.id)
    assert rec.reason == "chore approved"


async def test_reversal_line_carries_the_reversed_id(caplog, db_session, household, child_user):
    occ = await _occ(db_session, household, child_user)
    entry = await credit_earning(db_session, occurrence=occ)
    await db_session.flush()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=obs.AUDIT_LOGGER):
        comp = await reverse_entry(db_session, entry=entry, actor=None, reason="parent corrected")
        await db_session.flush()

    (rec,) = _events(caplog, "ledger.entry")
    assert rec.entry_id == str(comp.id)
    assert rec.reverses == str(entry.id)
    assert rec.amount_cents == -200


async def test_audit_record_emits_an_override_line(caplog, db_session, household, admin_user):
    with caplog.at_level(logging.INFO, logger=obs.AUDIT_LOGGER):
        await audit.record(
            db_session,
            action="occurrence.decision",
            entity_type="occurrence",
            entity_id="abc",
            actor=admin_user,
            before={"status": "needs_review"},
            after={"status": "verified_pass"},
        )
        await db_session.flush()

    (rec,) = _events(caplog, "audit.override")
    assert rec.action == "occurrence.decision"
    assert rec.actor == str(admin_user.id)
    assert rec.before == {"status": "needs_review"}
    assert rec.after == {"status": "verified_pass"}


async def test_verification_insert_emits_a_model_call_line(
    caplog, db_session, household, child_user
):
    occ = await _occ(db_session, household, child_user)
    with caplog.at_level(logging.INFO, logger=obs.AUDIT_LOGGER):
        db_session.add(
            Verification(
                occurrence_id=occ.id,
                kind="llm",
                verdict=Verdict.pass_,
                confidence=0.91,
                model_name="qwen2.5-vl",
                created_by="system",
            )
        )
        await db_session.flush()

    (rec,) = _events(caplog, "model.call")
    assert rec.verdict == "pass"
    assert rec.model == "qwen2.5-vl"
    assert rec.confidence == pytest.approx(0.91)
