"""Household backup: export the household to a JSON file, import one back (Phase 6).

Export is a plain authenticated GET so the PWA can hand it to the browser as a download,
the same way the per-kid statement CSV already does. Import replaces the household, so it
runs behind the admin dependency, refuses a bundle that would lock the caller out, and
re-issues their session — the restore deletes the one they arrived with.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.v1.auth import start_session
from app.auth.deps import AdminUser, DbDep
from app.models import Household
from app.schemas.export import ImportRequest, ImportResult
from app.services import audit
from app.services.export import ExportError, build_bundle, json_default, restore_bundle
from app.services.export import validate_bundle as validate_export_bundle

router = APIRouter(prefix="/admin", tags=["admin"])


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "household"


@router.get("/export")
async def export_household(
    db: DbDep,
    _: AdminUser,
    history: bool = True,
    money: bool = True,
) -> Response:
    """Download the household as one JSON bundle, with history and money by choice."""
    household = (await db.execute(select(Household).limit(1))).scalar_one()
    bundle = await build_bundle(db, history=history, money=money)
    day = datetime.now(UTC).date().isoformat()
    filename = f"chorekeeper-{_slug(household.name)}-{day}.json"
    return Response(
        content=json.dumps(bundle, default=json_default, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/import", response_model=ImportResult)
async def import_household(
    payload: ImportRequest,
    request: Request,
    response: Response,
    db: DbDep,
    admin: AdminUser,
) -> ImportResult:
    """Replace the household with a backup bundle. ``dry_run`` reports without writing."""
    try:
        if payload.dry_run:
            counts, warnings = validate_export_bundle(payload.bundle, actor=admin)
            return ImportResult(counts=counts, warnings=warnings, dry_run=True)
        counts, warnings, restored = await restore_bundle(db, payload.bundle, actor=admin)
    except ExportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    await audit.record(
        db,
        actor=restored,
        action="household.import",
        entity_type="household",
        entity_id=restored.household_id,
        after={"counts": counts, "options": payload.bundle.get("options")},
    )
    me = await start_session(restored, request, response, db)
    return ImportResult(counts=counts, warnings=warnings, csrf_token=me.csrf_token)
