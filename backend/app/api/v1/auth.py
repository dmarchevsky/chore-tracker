"""Authentication: local accounts + TOTP for admins (spec §12.1)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from app.auth import SESSION_COOKIE, ratelimit
from app.auth.deps import DbDep, current_user
from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.sessions import create_session, revoke_session
from app.auth.totp import new_secret, provisioning_uri, verify_code
from app.config import get_settings
from app.models import User, UserRole
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    TotpConfirmRequest,
    TotpEnrollResponse,
    TotpResetRequest,
)
from app.services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, session_id: str, *, max_age: int) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=max_age,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=MeResponse)
async def login(
    payload: LoginRequest, request: Request, response: Response, db: DbDep
) -> MeResponse:
    ip = _client_ip(request)
    if not ratelimit.ip_allowed(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts, slow down")
    if ratelimit.account_locked_for(payload.username) > 0:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "account temporarily locked")

    user = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()

    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    password_ok = user is not None and verify_password(user.password_hash, payload.password)
    if user is None or not user.is_active or not password_ok:
        ratelimit.record_failure(payload.username)
        raise invalid

    if user.role == UserRole.admin and user.totp_enrolled:
        # TOTP mandatory once enrolled. A not-yet-enrolled admin may log in with a
        # password alone to reach the enrollment endpoint (documented bootstrap).
        if not user.totp_secret or not verify_code(user.totp_secret, payload.totp_code or ""):
            ratelimit.record_failure(payload.username)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing TOTP code")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    ratelimit.record_success(payload.username)
    session = await create_session(db, user, user_agent=request.headers.get("user-agent"), ip=ip)
    max_age = int((session.expires_at - session.created_at).total_seconds())
    _set_session_cookie(response, str(session.id), max_age=max_age)
    return _me(user, session.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: DbDep) -> Response:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        await revoke_session(db, sid)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeResponse)
async def me(request: Request, db: DbDep) -> MeResponse:
    from app.auth.sessions import load_session

    sid = request.cookies.get(SESSION_COOKIE)
    loaded = await load_session(db, sid) if sid else None
    if loaded is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    session_row, user = loaded
    return _me(user, session_row.csrf_token)


@router.post("/totp/enroll", response_model=TotpEnrollResponse)
async def totp_enroll(user: Annotated[User, Depends(current_user)]) -> TotpEnrollResponse:
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    if user.totp_enrolled:
        raise HTTPException(status.HTTP_409_CONFLICT, "TOTP already enrolled")
    secret = new_secret()
    user.totp_secret = secret
    return TotpEnrollResponse(
        secret=secret, provisioning_uri=provisioning_uri(secret, user.username)
    )


@router.post("/totp/confirm", response_model=MeResponse)
async def totp_confirm(
    payload: TotpConfirmRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: DbDep,
) -> MeResponse:
    if user.role != UserRole.admin or not user.totp_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "start enrollment first")
    if not verify_code(user.totp_secret, payload.totp_code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "code did not verify")
    user.totp_enrolled = True
    from app.auth.sessions import load_session

    loaded = await load_session(db, request.cookies.get(SESSION_COOKIE) or "")
    csrf = loaded[0].csrf_token if loaded else ""
    return _me(user, csrf)


@router.post("/totp/reset", response_model=MeResponse)
async def totp_reset(
    payload: TotpResetRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: DbDep,
) -> MeResponse:
    """Re-authenticate, then clear TOTP so the admin can enroll a new phone (spec §12.1)."""
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
    if payload.password is not None:
        ok = verify_password(user.password_hash, payload.password)
    else:
        ok = bool(user.totp_secret) and verify_code(user.totp_secret, payload.totp_code or "")
    if not ok:
        ratelimit.record_failure(user.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "re-authentication failed")

    user.totp_secret = None
    user.totp_enrolled = False
    await audit.record(db, actor=user, action="totp.reset", entity_type="user", entity_id=user.id)
    from app.auth.sessions import load_session

    loaded = await load_session(db, request.cookies.get(SESSION_COOKIE) or "")
    csrf = loaded[0].csrf_token if loaded else ""
    return _me(user, csrf)


def _me(user: User, csrf_token: str) -> MeResponse:
    return MeResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        csrf_token=csrf_token,
        totp_enrolled=user.totp_enrolled,
    )
