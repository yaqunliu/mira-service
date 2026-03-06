"""make novel_id chapter_id nullable in creations

Revision ID: make_nullable_001
Revises: 20251230_add_audio_video_url
Create Date: 2026-02-27 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'make_nullable_001'
down_revision = '20251230_add_audio_video_url'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('creations', 'novel_id', nullable=True)
    op.alter_column('creations', 'chapter_id', nullable=True)


def downgrade() -> None:
    op.alter_column('creations', 'novel_id', nullable=False)
    op.alter_column('creations', 'chapter_id', nullable=False)
