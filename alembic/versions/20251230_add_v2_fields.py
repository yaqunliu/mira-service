"""add_v2_fields

Revision ID: 20251230_add_v2_fields
Revises: 20251230_add_creation_fields
Create Date: 2025-12-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251230_add_v2_fields'
down_revision = '20251230_add_creation_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add V2 fields to creations table
    op.add_column('creations', sa.Column('video_generation_mode', sa.String(length=20), server_default='old', nullable=True))
    op.add_column('creations', sa.Column('video_generation_strategy', sa.String(length=20), server_default='ai_video', nullable=True))
    op.add_column('creations', sa.Column('audio_strategy', sa.String(length=20), server_default='tts', nullable=True))
    op.add_column('creations', sa.Column('character_feature_library_url', sa.String(length=500), nullable=True))
    op.add_column('creations', sa.Column('character_feature_library', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('creations', sa.Column('timeline_config', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('creations', sa.Column('editing_status', sa.String(length=20), nullable=True))

    # Add V2 fields to shots table
    op.add_column('shots', sa.Column('script_content', sa.Text(), nullable=True))
    op.add_column('shots', sa.Column('camera_movement', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('shots', sa.Column('dialogue_info', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('shots', sa.Column('character_actions', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('shots', sa.Column('frame_composition', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('shots', sa.Column('audio_evaluation', sa.String(length=20), nullable=True))
    op.add_column('shots', sa.Column('onscreen_characters', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('shots', sa.Column('voice_characters', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    # Remove V2 fields from creations table
    op.drop_column('creations', 'video_generation_mode')
    op.drop_column('creations', 'video_generation_strategy')
    op.drop_column('creations', 'audio_strategy')
    op.drop_column('creations', 'character_feature_library_url')
    op.drop_column('creations', 'character_feature_library')
    op.drop_column('creations', 'timeline_config')
    op.drop_column('creations', 'editing_status')

    # Remove V2 fields from shots table
    op.drop_column('shots', 'script_content')
    op.drop_column('shots', 'camera_movement')
    op.drop_column('shots', 'dialogue_info')
    op.drop_column('shots', 'character_actions')
    op.drop_column('shots', 'frame_composition')
    op.drop_column('shots', 'audio_evaluation')
    op.drop_column('shots', 'onscreen_characters')
    op.drop_column('shots', 'voice_characters')
