"""Authentication: Google identity via Cloudflare Access, plus break-glass (spec §12.1)."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.auth import SESSION_COOKIE, ratelimit
from app.auth.cf_access import access_email, is_lan_door
from app.auth.deps import DbDep
from app.auth.passwords import hash_password, needs_rehash, verify_password
from app.auth.sessions import create_session, load_session, revoke_session
from app.config import get_settings
from app.models import User, UserRole
from app.net import client_ip
from app.schemas.auth import (
    BreakGlassLoginRequest,
    DevLoginRequest,
    DevUser,
    LogoutResponse,
    MeResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Same logger as the Access middleware: a sign-in that fails is one story whichever half
# of it turned the person away, and an operator should only have to grep one name.
log = logging.getLogger("chorekeeper.api")


def _set_session_cookie(
    response: Response, session_id: str, *, max_age: int, lan_door: bool = False
) -> None:
    s = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        session_id,
        max_age=max_age,
        httponly=True,
        # Always Secure once internet-facing — except on the LAN break-glass door, which is
        # plain HTTP on a private address. A Secure cookie is simply never sent back over it,
        # so the login would succeed and the session would vanish on the next request, which
        # is no way back in at all. Nothing is given away: that door is already plaintext, so
        # anyone who could read the cookie could read the whole exchange (spec §12.1).
        secure=not lan_door and (s.cookie_secure or s.is_prod),
        samesite="lax",
        path="/",
    )


async def start_session(user: User, request: Request, response: Response, db: DbDep) -> MeResponse:
    session = await create_session(
        db, user, user_agent=request.headers.get("user-agent"), ip=client_ip(request)
    )
    max_age = int((session.expires_at - session.created_at).total_seconds())
    _set_session_cookie(response, str(session.id), max_age=max_age, lan_door=is_lan_door(request))
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
        # Behind Access this is close to impossible — the middleware 403s a request with no
        # assertion long before it reaches here — so seeing it in production is itself the
        # finding: the door is the LAN one, or CF_ACCESS_* is unset and the check is not
        # installed at all. INFO, because on the dev stack and the LAN door it is simply
        # what every page load looks like before anyone has signed in.
        log.info(
            "sign-in probe carried no Access identity",
            extra={
                "event": "auth.no_identity",
                "lan_door": is_lan_door(request),
                "client_ip": client_ip(request),
            },
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.is_active:
        # Name the address. The parent's next move is to add exactly this string under
        # Kids, and guessing which of a family's Google accounts the phone picked is the
        # kind of dead end that gets an app abandoned.
        #
        # Log it too. Somebody was actually turned away here, and without a line for it the
        # only evidence a failed sign-in leaves behind is an access-log 403 with no address
        # on it — which is no help at all when the phone is in another room.
        log.warning(
            "turned away a Google account that is not a member",
            extra={"event": "auth.not_a_member", "email": email, "inactive": user is not None},
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{email} is signed in to Google but is not an active member of this household",
        )
    return await start_session(user, request, response, db)


@router.post("/login", response_model=MeResponse)
async def break_glass_login(
    payload: BreakGlassLoginRequest, request: Request, response: Response, db: DbDep
) -> MeResponse:
    """Local admin password — the way back in when Cloudflare or Google is unavailable.

    Reachable on the LAN door and the host's loopback only: the tunnel's Caddy site answers
    404 for this path, so it never rides the tunnel (see docs/remote-access.md).
    """
    # Dev mode has no break-glass: there is nothing to break out of when the whole stack
    # signs you in by name, and a second password path would only be one more thing that can
    # drift from what production actually does. 404, so the door does not appear to exist.
    if get_settings().dev_auth:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")

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
    return await start_session(user, request, response, db)


def _require_dev_auth() -> None:
    """404 unless the dev sign-in is switched on — the route must not exist otherwise."""
    if not get_settings().dev_auth:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")


@router.get("/dev/users", response_model=list[DevUser])
async def dev_users(db: DbDep) -> list[User]:
    """Who a local developer can sign in as (DEV_AUTH only).

    The dev stack has no Cloudflare in front of it and no break-glass behind it, so this list
    plus the click below is the entire way in. It is safe only because create_app() refuses to
    start a prod app with DEV_AUTH set (spec §12.1).
    """
    _require_dev_auth()
    users = (await db.execute(select(User).where(User.is_active))).scalars().all()
    # Parents first — the admin screens are what a developer usually wants.
    return sorted(users, key=lambda u: (u.role != UserRole.admin, u.display_name.lower()))


@router.post("/dev/login", response_model=MeResponse)
async def dev_login(
    payload: DevLoginRequest, request: Request, response: Response, db: DbDep
) -> MeResponse:
    """Become the named user, no password (DEV_AUTH only).

    Deliberately routed through the same start_session() as every other sign-in, so sessions,
    CSRF and cookie lifetimes are exercised locally exactly as they behave in production.
    """
    _require_dev_auth()
    user = (
        await db.execute(select(User).where(User.id == payload.user_id, User.is_active))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such user")
    return await start_session(user, request, response, db)


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request, response: Response, db: DbDep) -> LogoutResponse:
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        await revoke_session(db, sid)
    response.delete_cookie(SESSION_COOKIE, path="/")
    # Dropping our own cookie is not a logout while the Access session stands — the next
    # page load would sign the same Google account straight back in. The SPA sends the
    # browser here to end the edge session too.
    #
    # It must be the TEAM domain with ?returnTo=, not the app host's /cdn-cgi/access/logout:
    # the latter answers 200 with a bare Cloudflare page, clears no cookie and offers no way
    # back, so the visitor is stranded and still signed in. The team-domain form 302s home
    # after expiring CF_Authorization, CF_Binding and CF_Device.
    s = get_settings()
    if not s.cf_access_team_domain:
        return LogoutResponse(access_logout_url=None)
    return_to = urlencode({"returnTo": s.public_base_url.rstrip("/") + "/"})
    return LogoutResponse(
        access_logout_url=(f"https://{s.cf_access_team_domain}/cdn-cgi/access/logout?{return_to}")
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
