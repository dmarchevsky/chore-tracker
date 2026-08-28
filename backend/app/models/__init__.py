"""SQLAlchemy models. Import every module here so Alembic autogenerate sees them."""

from app.models.audit import AuditLog
from app.models.chore import AssignmentMode, Chore, ProofType, VerificationMode
from app.models.household import Household
from app.models.occurrence import (
    SUBMITTABLE,
    TERMINAL,
    ChoreOccurrence,
    OccurrenceStatus,
)
from app.models.session import Session
from app.models.user import User, UserRole

__all__ = [
    "SUBMITTABLE",
    "TERMINAL",
    "AssignmentMode",
    "AuditLog",
    "Chore",
    "ChoreOccurrence",
    "Household",
    "OccurrenceStatus",
    "ProofType",
    "Session",
    "User",
    "UserRole",
    "VerificationMode",
]
