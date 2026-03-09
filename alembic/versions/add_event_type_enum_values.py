"""Add SESSION_RESET and INTERRUPT to event_type_enum

Revision ID: add_event_type_values
Revises: make_nullable_001
Create Date: 2026-03-09 00:00:00.000000

"""
from alembic import op


revision = 'add_event_type_values'
down_revision = 'make_nullable_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'SESSION_RESET'")
    op.execute("ALTER TYPE event_type_enum ADD VALUE IF NOT EXISTS 'INTERRUPT'")


def downgrade() -> None:
    pass
