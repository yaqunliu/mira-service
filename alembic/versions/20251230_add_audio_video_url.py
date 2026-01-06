"""add_audio_and_video_url_to_shots

Revision ID: 20251230_add_audio_video_url
Revises: 20251230_add_image_url
Create Date: 2025-12-30 17:20:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20251230_add_audio_video_url'
down_revision = '20251230_add_image_url'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    
    # Add audio_url column to shots if it doesn't exist
    if 'audio_url' not in shot_columns:
        op.add_column('shots', sa.Column('audio_url', sa.String(length=500), nullable=True))
        print("Added audio_url column to shots table")
    else:
        print("audio_url column already exists in shots table")
        
    # Add video_url column to shots if it doesn't exist
    if 'video_url' not in shot_columns:
        op.add_column('shots', sa.Column('video_url', sa.String(length=500), nullable=True))
        print("Added video_url column to shots table")
    else:
        print("video_url column already exists in shots table")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    
    if 'audio_url' in shot_columns:
        op.drop_column('shots', 'audio_url')
        
    if 'video_url' in shot_columns:
        op.drop_column('shots', 'video_url')
