"""FastAPI auth dependencies."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CSRF_HEADER, SESSION_COOKIE
from app.auth.sessions import load_session
from app.db import get_session
from app.models import Session as SessionRow
from app.models import User

DbDep = Annotated[AsyncSession, Depends(get_session)]

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def current_auth(request: Request, db: DbDep) -> tuple[SessionRow, User]:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    loaded = await load_session(db, session_id)
    if loaded is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired session")
    session_row, user = loaded
    if request.method not in _SAFE_METHODS:
        supplied = request.headers.get(CSRF_HEADER)
        if not supplied or not _consteq(supplied, session_row.csrf_token):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "missing or invalid CSRF token")
    return session_row, user


async def current_user(auth: Annotated[tuple[SessionRow, User], Depends(current_auth)]) -> User:
    return auth[1]


async def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    return user


def require_self_or_admin(child_id_param: str = "child_id"):
    """Dependency factory: allow an admin, or a child acting on their own resource."""

    async def _dep(request: Request, user: Annotated[User, Depends(current_user)]) -> User:
        if user.is_admin:
            return user
        raw = request.path_params.get(child_id_param)
        try:
            target = uuid.UUID(str(raw))
        except (ValueError, TypeError):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found") from None
        if target != user.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "scoped to self")
        return user

    return _dep


def _consteq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)


CurrentUser = Annotated[User, Depends(current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
