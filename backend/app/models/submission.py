"""Proof submissions and their media (spec §3, §4.4, §7.1).

A Submission is one attempt against an occurrence: 1..n photos, a location check-in, or a
bare acknowledgement. The server receive time is authoritative; client EXIF is advisory
(spec §6.1). Media is content-addressed so dedup is free (spec §13.1).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, uuid_pk


class SubmissionKind(enum.StrEnum):
    photo = "photo"
    location = "location"
    acknowledgement = "acknowledgement"


class SubmissionSource(enum.StrEnum):
    camera = "camera"  # in-app getUserMedia capture (spec §6.1 default)
    gallery = "gallery"  # admin-enabled escape hatch -> flagged GALLERY_UPLOAD
    checkin_webhook = "checkin_webhook"  # POST /checkin/{token}


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = uuid_pk()
    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("chore_occurrences.id", ondelete="CASCADE"), index=True
    )
    submitter_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    kind: Mapped[SubmissionKind] = mapped_column(String(16))
    source: Mapped[SubmissionSource] = mapped_column(String(20), default=SubmissionSource.camera)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    client_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    # Anti-cheat / quality flags surfaced to the admin (spec §6.1). Inputs to routing,
    # never an auto-fail.
    flags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    # --- location check-in fields (spec §6.2) --------------------------------
    geo_lat: Mapped[float | None] = mapped_column(Numeric(9, 4), default=None)  # ~11m coarse
    geo_lon: Mapped[float | None] = mapped_column(Numeric(9, 4), default=None)
    geo_accuracy_m: Mapped[float | None] = mapped_column(Numeric(8, 1), default=None)
    geo_distance_m: Mapped[float | None] = mapped_column(Numeric(9, 1), default=None)
    geo_within: Mapped[bool | None] = mapped_column(default=None)
    geo_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    media: Mapped[list[SubmissionMedia]] = relationship(
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="SubmissionMedia.idx",
        lazy="selectin",
    )


class SubmissionMedia(TimestampMixin, Base):
    __tablename__ = "submission_media"
    __table_args__ = (UniqueConstraint("submission_id", "idx", name="uq_submission_media_idx"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    submission_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("submissions.id", ondelete="CASCADE"), index=True
    )
    idx: Mapped[int] = mapped_column(Integer, default=0)  # matches photo_prompts order
    prompt_label: Mapped[str | None] = mapped_column(String(120), default=None)

    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str | None] = mapped_column(String(32), index=True, default=None)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    mime: Mapped[str] = mapped_column(String(40), default="image/jpeg")
    storage_path: Mapped[str] = mapped_column(String(255))
    exif: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    # Retention (spec §14 Q2): after MEDIA_RETENTION_DAYS the original is deleted and only
    # a 256px thumbnail (+ the verdict, on the verification row) is kept.
    thumbnail_path: Mapped[str | None] = mapped_column(String(255), default=None)
    original_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    submission: Mapped[Submission] = relationship(back_populates="media")
