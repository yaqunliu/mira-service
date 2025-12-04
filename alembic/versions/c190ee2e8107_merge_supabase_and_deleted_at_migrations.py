"""merge supabase and deleted_at migrations

Revision ID: c190ee2e8107
Revises: add_deleted_at_002, add_supabase_user_id
Create Date: 2025-12-04 15:45:06.819500

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c190ee2e8107'
down_revision = ('add_deleted_at_002', 'add_supabase_user_id')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
