"""merge_status_and_v2_heads

Revision ID: 626514ef1203
Revises: 20251230_fix_status_columns, 20251230_v2_schema_final
Create Date: 2025-12-29 17:09:23.690081

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '626514ef1203'
down_revision = ('20251230_fix_status_columns', '20251230_v2_schema_final')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
