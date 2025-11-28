"""Add voice_id column to creations

Revision ID: a1b2c3d4e5f6
Revises: 25c2048957a6
Create Date: 2025-11-27 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '25c2048957a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 voice_id 列到 creations 表
    op.add_column('creations', sa.Column('voice_id', sa.String(length=100), nullable=True))


def downgrade() -> None:
    # 删除 voice_id 列
    op.drop_column('creations', 'voice_id')

