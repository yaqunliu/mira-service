"""Add voice_speed column to creations

Revision ID: e4f5g6h7i8j9
Revises: c3d4e5f6g7h8
Create Date: 2025-11-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e4f5g6h7i8j9'
down_revision = 'c3d4e5f6g7h8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 voice_speed 列到 creations 表
    # 默认值为 1.0，范围 0-10
    op.add_column('creations', sa.Column('voice_speed', sa.Float(), nullable=False, server_default='1.0'))


def downgrade() -> None:
    # 删除 voice_speed 列
    op.drop_column('creations', 'voice_speed')

