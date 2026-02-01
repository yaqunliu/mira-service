"""Merge voice fields and deleted_at migrations

Revision ID: d6cc165dc7f0
Revises: 457aceb35eb0, xxxx001_add_voice_fields
Create Date: 2026-02-01 07:02:15.394095

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd6cc165dc7f0'
down_revision = ('457aceb35eb0', 'xxxx001_add_voice_fields')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
