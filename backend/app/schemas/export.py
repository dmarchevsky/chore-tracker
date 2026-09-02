"""Request/response shapes for the household backup endpoints (see services/export.py)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportRequest(BaseModel):
    """The parsed contents of a backup file, as the admin Settings screen uploads it."""

    model_config = ConfigDict(extra="forbid")

    bundle: dict[str, Any]
    #: Validate and report what would happen, changing nothing. Used to build the
    #: confirmation prompt before a replace.
    dry_run: bool = False


class ImportResult(BaseModel):
    """What the import did (or would do), plus the session that replaced the caller's."""

    counts: dict[str, int]
    warnings: list[str] = Field(default_factory=list)
    dry_run: bool = False
    #: A restore deletes every session, including the caller's. The importer mints a fresh
    #: one for the restored parent account; the PWA must start sending this token.
    csrf_token: str | None = None
