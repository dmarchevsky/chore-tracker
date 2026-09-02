"""google auth via cloudflare access

Replaces local password + TOTP identity with the Google address Cloudflare Access
authenticates (spec §12.1). One local admin password survives as break-glass, so
``password_hash`` becomes nullable rather than being dropped; every child row loses
the one it had.

Revision ID: 9c1e4b0a7d21
Revises: 563533ab7236
Create Date: 2026-09-01 21:40:00.000000
"""
from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '9c1e4b0a7d21'
down_revision: str | None = '563533ab7236'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The address to stamp onto an admin that already exists — this matters when converting a
# database that predates Google sign-in. No default: a hardcoded one binds somebody's real
# account on any deploy that leaves ADMIN_EMAIL unset. A fresh install has no users here at
# all (this runs before anything creates them), and app/bootstrap.py does that job instead.
_ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()


def upgrade() -> None:
    op.add_column('users', sa.Column('email', sa.String(length=320), nullable=True))
    op.create_unique_constraint('uq_user_email', 'users', ['household_id', 'email'])

    # Give an existing parent an identity to sign in with; without this the migration locks
    # the only admin out of the app it just converted. Skipped when unset — there is nothing
    # safe to guess, and on a new database there is no row to update anyway.
    if _ADMIN_EMAIL:
        op.execute(
            sa.text(
                "UPDATE users SET email = :email WHERE role = 'admin' AND email IS NULL"
            ).bindparams(email=_ADMIN_EMAIL)
        )

    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=True)
    # Children authenticate through Access only — leaving a hash behind would leave a
    # second, weaker door open on the break-glass port.
    op.execute("UPDATE users SET password_hash = NULL WHERE role <> 'admin'")

    op.drop_column('users', 'totp_enrolled')
    op.drop_column('users', 'totp_secret')


def downgrade() -> None:
    op.add_column(
        'users',
        sa.Column('totp_secret', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column(
            'totp_enrolled', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.alter_column('users', 'totp_enrolled', server_default=None)
    # Rows whose password was cleared cannot be restored; give them an unusable hash so the
    # NOT NULL constraint can go back on.
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=False)
    op.drop_constraint('uq_user_email', 'users', type_='unique')
    op.drop_column('users', 'email')
