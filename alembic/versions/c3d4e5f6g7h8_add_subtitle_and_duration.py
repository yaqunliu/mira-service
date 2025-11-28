"""Add subtitle_url to creations and audio_duration to shots

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2025-11-27 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6g7h8'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 subtitle_url 列到 creations 表
    op.add_column('creations', sa.Column('subtitle_url', sa.String(length=500), nullable=True))
    
    # 添加 audio_duration 列到 shots 表
    op.add_column('shots', sa.Column('audio_duration', sa.Integer(), nullable=True))


def downgrade() -> None:
    # 删除 audio_duration 列
    op.drop_column('shots', 'audio_duration')
    
    # 删除 subtitle_url 列
    op.drop_column('creations', 'subtitle_url')

