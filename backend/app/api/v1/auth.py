"""Authentication: Google identity via Cloudflare Access, plus break-glass (spec §12.1)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.auth import SESSION_COOKIE, ratelimit
from app.auth.cf_access import access_email
from app.auth.deps import DbDep
from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.sessions import create_session, load_session, revoke_session
from app.config import get_settings
from app.models import User, UserRole
from app.net import client_ip
from app.schemas.auth import BreakGlassLoginRequest, LogoutResponse, MeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, session_id: str, *, max_age: int) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=max_age,
        httponly=True,
        secure=s.cookie_secure or s.is_prod,  # always Secure once internet-facing
        samesite="lax",
        path="/",
    )


async def _start_session(user: User, request: Request, response: Response, db: DbDep) -> MeResponse:
    session = await create_session(
        db, user, user_agent=request.headers.get("user-agent"), ip=client_ip(request)
    )
    max_age = int((session.expires_at - session.created_at).total_seconds())
    _set_session_cookie(response, str(session.id), max_age=max_age)
    return _me(user, session.csrf_token)


@router.get("/me", response_model=MeResponse)
async def me(request: Request, response: Response, db: DbDep) -> MeResponse:
    """The SPA's bootstrap probe — and, behind Access, the login itself.

    Cloudflare has already made the visitor prove they own a Google address by the time
    this runs, so there is nothing left to ask them: map the address to a household member
    and mint the session. That is why there is no sign-in form for anyone but break-glass.
    """
    email = access_email(request)
    sid = request.cookies.get(SESSION_COOKIE)
    loaded = await load_session(db, sid) if sid else None
    if loaded is not None:
        session_row, user = loaded
        if email is None or user.email == email:
            return _me(user, session_row.csrf_token)
        # Access is authoritative about who is at the keyboard. A cookie naming someone
        # else is stale — a shared family tablet where the last kid never signed out —
        # and honouring it would hand one child another's screen.
        await revoke_session(db, sid)

    if email is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.is_active:
        # Name the address. The parent's next move is to add exactly this string under
        # Kids, and guessing which of a family's Google accounts the phone picked is the
        # kind of dead end that gets an app abandoned.
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{email} is signed in to Google but is not an active member of this household",
        )
    return await _start_session(user, request, response, db)


@router.post("/login", response_model=MeResponse)
async def break_glass_login(
    payload: BreakGlassLoginRequest, request: Request, response: Response, db: DbDep
) -> MeResponse:
    """Local admin password — the way back in when Cloudflare or Google is unavailable.

    Only reachable on the host's loopback port: the Caddy front door answers 404 for this
    path, so it is never exposed through the tunnel (see docs/remote-access.md).
    """
    ip = client_ip(request)
    if not ratelimit.ip_allowed(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts, slow down")
    if ratelimit.account_locked_for(payload.username) > 0:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "account temporarily locked")

    user = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()

    # Children have no password at all, so role is checked before the hash: a child row
    # can never satisfy this endpoint regardless of what is in the column.
    usable = user is not None and user.is_active and user.role == UserRole.admin
    password_ok = (
        usable
        and bool(user.password_hash)
        and verify_password(user.password_hash, payload.password)
    )
    if not password_ok:
        ratelimit.record_failure(payload.username)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    ratelimit.record_success(payload.username)
    return await _start_session(user, request, response, db)


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request, response: Response, db: DbDep) -> LogoutResponse:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        await revoke_session(db, sid)
    response.delete_cookie(SESSION_COOKIE, path="/")
    # Dropping our own cookie is not a logout while the Access session stands — the next
    # page load would sign the same Google account straight back in. The SPA sends the
    # browser here to end the edge session too.
    team = get_settings().cf_access_team_domain
    return LogoutResponse(
        access_logout_url=f"https://{team}/cdn-cgi/access/logout" if team else None
    )


def _me(user: User, csrf_token: str) -> MeResponse:
    return MeResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        csrf_token=csrf_token,
    )
