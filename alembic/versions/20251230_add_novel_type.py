"""add_type_field_to_novels

Revision ID: 20251230_add_novel_type
Revises: 20251229_manual_migration
Create Date: 2025-12-30 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251230_add_novel_type'
down_revision = '20251229_manual_migration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add type column to novels table
    # Set default to 'novel' and nullable=False
    op.add_column('novels', sa.Column('type', sa.String(length=20), server_default='novel', nullable=False))


def downgrade() -> None:
    # Remove type column from novels table
    op.drop_column('novels', 'type')

