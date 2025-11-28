"""Add audio_url column to shots

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2025-11-27 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 audio_url 列到 shots 表
    op.add_column('shots', sa.Column('audio_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    # 删除 audio_url 列
    op.drop_column('shots', 'audio_url')

