"""Whole-household export and restore (implementation-plan Phase 6: backup + tested restore).

Export walks the household's tables and emits one JSON bundle; import **replaces** the
household with the bundle's contents, re-using the original primary keys so that balances,
occurrence links and audit trails come back exactly as they were.

The parent chooses how much goes in the bundle: chore definitions always, chore history and
the money ledger by request. Secrets and per-device state never leave the house — sessions,
check-in tokens, push subscriptions, the notification log and the verification queue are not
exported at all, and neither is the vision-LLM API key nor the break-glass password hash
(spec §12.1). Photo bytes stay under ``MEDIA_ROOT``; only the media rows travel.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

import sqlalchemy as sa
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base
from app.models import (
    AuditLog,
    Chore,
    ChoreOccurrence,
    ChoreStateEvent,
    Dispute,
    Household,
    HouseholdSettings,
    LedgerEntry,
    Submission,
    SubmissionMedia,
    User,
    UserRole,
    Verification,
)

BUNDLE_VERSION = 1

#: Chore definitions and the people they belong to — always exported.
CORE: tuple[type[Base], ...] = (Household, User, HouseholdSettings, Chore)

#: What actually happened: occurrences, proof, verdicts, disputes, the admin audit trail.
HISTORY: tuple[type[Base], ...] = (
    ChoreOccurrence,
    ChoreStateEvent,
    Submission,
    SubmissionMedia,
    Verification,
    Dispute,
    AuditLog,
)

#: The append-only money ledger (spec §9).
MONEY: tuple[type[Base], ...] = (LedgerEntry,)

#: Every table a bundle may carry, in an order that satisfies the foreign keys on insert.
ORDER: tuple[type[Base], ...] = CORE + HISTORY + MONEY

#: Columns dropped on the way out. A backup file lands on somebody's laptop; a credential
#: has no business being in it. The break-glass password is set again after a restore.
REDACTED: dict[str, frozenset[str]] = {
    "household_settings": frozenset({"llm_api_key"}),
    "users": frozenset({"password_hash"}),
}


class ExportError(ValueError):
    """A bundle the importer refuses — wrong version, unknown table, unusable value."""


# --------------------------------------------------------------------------- export


async def build_bundle(db: AsyncSession, *, history: bool, money: bool) -> dict[str, Any]:
    """Serialise the household into a JSON-ready bundle."""
    models = [*CORE]
    if history:
        models += HISTORY
    if money:
        models += MONEY

    warnings: list[str] = []
    tables: dict[str, list[dict[str, Any]]] = {}
    for model in models:
        name = model.__tablename__
        redacted = REDACTED.get(name, frozenset())
        rows = (await db.execute(select(model.__table__))).mappings().all()
        tables[name] = [{k: v for k, v in row.items() if k not in redacted} for row in rows]

    if money and not history:
        # ledger_entries.occurrence_id points at a table this bundle does not carry. Drop the
        # link rather than the row: the amount, kind and reason are what a balance is made of.
        detached = 0
        for row in tables["ledger_entries"]:
            if row["occurrence_id"] is not None:
                row["occurrence_id"] = None
                detached += 1
        if detached:
            warnings.append(
                f"{detached} money entries lost their link to a chore occurrence "
                "because chore history was not included"
            )

    return {
        "version": BUNDLE_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "options": {"history": history, "money": money},
        "counts": {name: len(rows) for name, rows in tables.items()},
        "warnings": warnings,
        "tables": tables,
    }


def json_default(value: Any) -> str:
    """``json.dumps`` fallback for the types a bundle holds (UUID, datetimes, Decimal)."""
    return str(value)


# --------------------------------------------------------------------------- import


def validate_bundle(bundle: Any, *, actor: User) -> tuple[dict[str, int], list[str]]:
    """Check a bundle can be restored without breaking anything, and count what it holds.

    Raises :class:`ExportError` with a sentence a parent can act on. Touches no database.
    """
    if not isinstance(bundle, Mapping):
        raise ExportError("this file is not a ChoreKeeper backup")
    if bundle.get("version") != BUNDLE_VERSION:
        raise ExportError(
            f"backup format version {bundle.get('version')!r} — this ChoreKeeper reads "
            f"version {BUNDLE_VERSION}"
        )
    tables = bundle.get("tables")
    if not isinstance(tables, Mapping):
        raise ExportError("this backup has no tables in it")

    known = {model.__tablename__ for model in ORDER}
    unknown = sorted(set(tables) - known)
    if unknown:
        raise ExportError(f"backup contains table(s) this version does not know: {unknown}")
    missing = sorted(m.__tablename__ for m in CORE if m.__tablename__ not in tables)
    if missing:
        raise ExportError(f"backup is missing required table(s): {missing}")
    for name, rows in tables.items():
        if not isinstance(rows, Sequence) or isinstance(rows, str | bytes):
            raise ExportError(f"backup table {name!r} is not a list of rows")

    if not _find_admin_row(tables["users"], actor):
        who = actor.email or actor.username
        raise ExportError(
            f"this backup has no active parent account for {who} — importing it would lock "
            "you out, so it was refused"
        )

    warnings = [str(w) for w in bundle.get("warnings", [])]
    if not bundle.get("options", {}).get("money", "ledger_entries" in tables):
        warnings.append("this backup carries no money entries — every balance restores to zero")
    warnings.append(
        "the break-glass password is never included in a backup — set it again in Settings"
    )
    return {name: len(rows) for name, rows in tables.items()}, warnings


async def restore_bundle(
    db: AsyncSession, bundle: Mapping[str, Any], *, actor: User
) -> tuple[dict[str, int], list[str], User]:
    """Replace the household with the bundle. Returns counts, warnings and the restored admin.

    Never commits: the caller's request-scoped session does, so a failure anywhere leaves the
    household exactly as it was.
    """
    _, warnings = validate_bundle(bundle, actor=actor)
    tables: Mapping[str, list[dict[str, Any]]] = bundle["tables"]
    # Read the caller's identity now — the row backing it is about to be deleted.
    actor_email, actor_username = actor.email, actor.username

    await db.execute(delete(Household))
    await db.flush()
    # The cascade took the caller's user and session rows with it, but the identity map still
    # holds those objects. Forget them, or re-inserting the same primary keys collides.
    db.expunge_all()

    counts: dict[str, int] = {}
    reversals: list[tuple[uuid.UUID, uuid.UUID]] = []
    admin: User | None = None

    for model in ORDER:
        name = model.__tablename__
        rows = tables.get(name) or []
        for raw in rows:
            data = _coerce(model, raw)
            if model is LedgerEntry and data.get("reversed_by_entry_id") is not None:
                reversals.append((data["id"], data["reversed_by_entry_id"]))
                data["reversed_by_entry_id"] = None
            obj = model(**data)
            db.add(obj)
            if model is User and _is_actor(raw, actor_email, actor_username):
                admin = obj
        counts[name] = len(rows)
        await db.flush()

    for entry_id, reversed_by in reversals:
        # The self-FK points *forward* to the reversing entry, which does not exist yet when
        # the original is inserted. Setting it in a second pass re-creates the row exactly as
        # it was exported — restore machinery, not a correction to a settled amount (spec §9).
        await db.execute(
            update(LedgerEntry)
            .where(LedgerEntry.id == entry_id)
            .values(reversed_by_entry_id=reversed_by)
        )

    if admin is None:  # pragma: no cover - validate_bundle already proved it is there
        raise ExportError("restored backup has no parent account for you")
    return counts, warnings, admin


def _find_admin_row(rows: Sequence[Any], actor: User) -> dict[str, Any] | None:
    for row in rows:
        if isinstance(row, Mapping) and _is_actor(row, actor.email, actor.username):
            return dict(row)
    return None


def _is_actor(row: Mapping[str, Any], email: str | None, username: str) -> bool:
    """Is this exported user row the parent who is doing the import?

    Matched on the Google address that signs them in, falling back to the username for a
    break-glass admin that has none.
    """
    if row.get("role") != UserRole.admin or not row.get("is_active", True):
        return False
    if email:
        return isinstance(row.get("email"), str) and row["email"].lower() == email.lower()
    return row.get("email") is None and row.get("username") == username


def _coerce(model: type[Base], raw: Any) -> dict[str, Any]:
    """Turn one JSON-decoded row back into column values the driver accepts."""
    if not isinstance(raw, Mapping):
        raise ExportError(f"{model.__tablename__}: a row is not an object")
    columns = model.__table__.columns
    unknown = sorted(set(raw) - set(columns.keys()))
    if unknown:
        raise ExportError(f"{model.__tablename__}: unknown column(s) {unknown}")
    out: dict[str, Any] = {}
    for key, value in raw.items():
        try:
            out[key] = _value(columns[key].type, value)
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise ExportError(f"{model.__tablename__}.{key}: {value!r} is not usable") from exc
    return out


def _value(coltype: sa.types.TypeEngine[Any], value: Any) -> Any:
    if value is None:
        return None
    if isinstance(coltype, sa.ARRAY):
        if not isinstance(value, list):
            raise TypeError("expected a list")
        return [_value(coltype.item_type, item) for item in value]
    if isinstance(coltype, sa.Uuid):
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    if isinstance(coltype, sa.DateTime):
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)
    if isinstance(coltype, sa.Date):
        return value if isinstance(value, date) else date.fromisoformat(value)
    if isinstance(coltype, sa.Time):
        return value if isinstance(value, time) else time.fromisoformat(value)
    if isinstance(coltype, sa.Numeric):
        return value if isinstance(value, Decimal) else Decimal(str(value))
    return value
