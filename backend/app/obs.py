"""Structured JSON logging + an audit stream for money, overrides and model calls (spec §5).

Every ledger entry, audit-log row and verification is also emitted as a single-line JSON
log record carrying the actor, a UTC timestamp and the before/after (where the DB row has
it). The DB tables remain the durable trail; these lines are what a log shipper indexes.

Import side effect: ORM ``after_insert`` listeners are registered on first import. Call
:func:`configure_logging` once at process start to install the JSON formatter.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event

from app.config import get_settings
from app.models import AuditLog, LedgerEntry, Verification

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}

AUDIT_LOGGER = "chorekeeper.audit"


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, msg, + any ``extra=`` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(*, force: bool = False) -> None:
    """Install the root handler. ``LOG_FORMAT=text`` keeps the human formatter for dev."""
    root = logging.getLogger()
    if root.handlers and not force:
        return
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if get_settings().log_format.lower() == "text":
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


# --- audit stream ------------------------------------------------------------

_audit_log = logging.getLogger(AUDIT_LOGGER)


def _emit(event_name: str, **fields: Any) -> None:
    _audit_log.info(event_name, extra={"event": event_name, **fields})


def log_ledger_entry(entry: LedgerEntry) -> None:
    """Emit one ``ledger.entry`` audit line. Called explicitly from ``services.ledger``
    because the exactly-once earning/penalty path is a Core INSERT (no ORM event)."""
    meta = entry.meta or {}
    _emit(
        "ledger.entry",
        entry_id=str(entry.id),
        kind=str(entry.kind),
        amount_cents=entry.amount_cents,
        child_id=str(entry.child_id),
        occurrence_id=str(entry.occurrence_id) if entry.occurrence_id else None,
        actor=str(entry.actor_user_id) if entry.actor_user_id else entry.created_by,
        reason=entry.reason,
        reverses=meta.get("reverses_entry_id"),
    )


@event.listens_for(AuditLog, "after_insert")
def _log_audit_row(_mapper, _conn, row: AuditLog) -> None:
    _emit(
        "audit.override",
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        actor=str(row.actor_user_id) if row.actor_user_id else row.actor_kind,
        before=row.before,
        after=row.after,
    )


@event.listens_for(Verification, "after_insert")
def _log_verification(_mapper, _conn, v: Verification) -> None:
    _emit(
        "model.call" if v.kind == "llm" else "verification.manual",
        verification_id=str(v.id),
        occurrence_id=str(v.occurrence_id),
        kind=str(v.kind),
        verdict=str(v.verdict),
        confidence=float(v.confidence) if v.confidence is not None else None,
        model=v.model_name,
        actor=str(v.actor_user_id) if v.actor_user_id else v.created_by,
    )
