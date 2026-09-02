"""User lookups shared by the routers that write an email address.

``users.email`` is the sign-in identity for everyone (spec §12.1) and is unique per
household, so the check belongs in one place: the kid path and the parent's own profile
both enforce it, and a second copy is a second thing to keep in step.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def email_taken(db: AsyncSession, email: str, *, excluding: uuid.UUID | None = None) -> bool:
    """Is this address already somebody's sign-in identity?

    ``excluding`` skips one user's own row, so re-saving a profile without changing the
    address is not a conflict with itself.
    """
    stmt = select(User.id).where(User.email == email.strip().lower())
    if excluding is not None:
        stmt = stmt.where(User.id != excluding)
    return (await db.execute(stmt)).first() is not None
