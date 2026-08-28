"""Server-side session lifecycle."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Session as SessionRow
from app.models import User, UserRole


def _now() -> datetime:
    return datetime.now(UTC)


async def create_session(
    db: AsyncSession, user: User, *, user_agent: str | None, ip: str | None
) -> SessionRow:
    s = get_settings()
    lifetime = (
        timedelta(hours=s.admin_session_hours)
        if user.role == UserRole.admin
        else timedelta(days=s.child_session_days)
    )
    row = SessionRow(
        user_id=user.id,
        csrf_token=secrets.token_urlsafe(32),
        expires_at=_now() + lifetime,
        user_agent=(user_agent or "")[:256] or None,
        ip=ip,
    )
    db.add(row)
    await db.flush()
    return row


async def load_session(db: AsyncSession, session_id: str) -> tuple[SessionRow, User] | None:
    try:
        sid = uuid.UUID(session_id)
    except (ValueError, TypeError):
        return None
    row = await db.get(SessionRow, sid)
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at <= _now():
        return None
    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return row, user


async def revoke_session(db: AsyncSession, session_id: str) -> None:
    try:
        sid = uuid.UUID(session_id)
    except (ValueError, TypeError):
        return
    row = await db.get(SessionRow, sid)
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()


async def revoke_user_sessions(db: AsyncSession, user_id: uuid.UUID) -> int:
    """Revoke every live session for a user — on deactivation or a password reset."""
    result = await db.execute(
        update(SessionRow)
        .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=_now())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0
