"""SQLAlchemy models. Import every module here so Alembic autogenerate sees them."""

from app.models.audit import AuditLog
from app.models.chore import AssignmentMode, Chore, ProofType, VerificationMode
from app.models.household import Household
from app.models.ledger import EARN_KINDS, LedgerEntry, LedgerKind
from app.models.occurrence import (
    SUBMITTABLE,
    TERMINAL,
    ChoreOccurrence,
    OccurrenceStatus,
)
from app.models.session import Session
from app.models.submission import (
    Submission,
    SubmissionKind,
    SubmissionMedia,
    SubmissionSource,
)
from app.models.user import User, UserRole
from app.models.verification import Verdict, Verification, VerificationKind

__all__ = [
    "EARN_KINDS",
    "SUBMITTABLE",
    "TERMINAL",
    "AssignmentMode",
    "AuditLog",
    "Chore",
    "ChoreOccurrence",
    "Household",
    "LedgerEntry",
    "LedgerKind",
    "OccurrenceStatus",
    "ProofType",
    "Session",
    "Submission",
    "SubmissionKind",
    "SubmissionMedia",
    "SubmissionSource",
    "User",
    "UserRole",
    "Verdict",
    "Verification",
    "VerificationKind",
    "VerificationMode",
]
