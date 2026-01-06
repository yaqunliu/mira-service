"""add_v2_safe

Revision ID: 20251230_add_v2_safe
Revises: 20251230_add_status_fields
Create Date: 2025-12-30 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20251230_add_v2_safe'
down_revision = '20251230_add_status_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # 1. SCENES Table
    scene_columns = [c['name'] for c in inspector.get_columns('scenes')]
    
    # Environment & Scene Graph V2 fields
    if 'environment_setting' not in scene_columns:
        op.add_column('scenes', sa.Column('environment_setting', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    
    if 'scene_graph_prompt' not in scene_columns:
        op.add_column('scenes', sa.Column('scene_graph_prompt', sa.Text(), nullable=True))
        
    if 'scene_graph_url' not in scene_columns:
        op.add_column('scenes', sa.Column('scene_graph_url', sa.String(length=500), nullable=True))
        
    # High Quality Generation V2 fields
    if 'environment_images' not in scene_columns:
        op.add_column('scenes', sa.Column('environment_images', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        
    if 'lighting_info' not in scene_columns:
        op.add_column('scenes', sa.Column('lighting_info', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        
    if 'environment_details' not in scene_columns:
        op.add_column('scenes', sa.Column('environment_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # 2. SHOTS Table
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    
    # AI Video & Audio Strategy fields (potentially missing)
    if 'video_prompt' not in shot_columns:
        op.add_column('shots', sa.Column('video_prompt', sa.Text(), nullable=True))
        
    if 'video_duration' not in shot_columns:
        op.add_column('shots', sa.Column('video_duration', sa.Integer(), nullable=True))
        
    if 'video_status' not in shot_columns:
        op.add_column('shots', sa.Column('video_status', sa.String(length=20), nullable=True))
        
    if 'audio_strategy' not in shot_columns:
        op.add_column('shots', sa.Column('audio_strategy', sa.String(length=20), nullable=True))

    # 3. CHARACTERS Table (Safety check for basic info that might be missing in older schemas)
    char_columns = [c['name'] for c in inspector.get_columns('characters')]
    
    if 'basic_info' not in char_columns:
        op.add_column('characters', sa.Column('basic_info', sa.String(length=500), nullable=True))
    
    if 'tags' not in char_columns:
        op.add_column('characters', sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Scenes
    scene_columns = [c['name'] for c in inspector.get_columns('scenes')]
    fields_to_drop_scenes = [
        'environment_setting', 'scene_graph_prompt', 'scene_graph_url', 
        'environment_images', 'lighting_info', 'environment_details'
    ]
    for field in fields_to_drop_scenes:
        if field in scene_columns:
            op.drop_column('scenes', field)

    # Shots
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    fields_to_drop_shots = [
        'video_prompt', 'video_duration', 'video_status', 'audio_strategy'
    ]
    for field in fields_to_drop_shots:
        if field in shot_columns:
            op.drop_column('shots', field)

    # Characters
    char_columns = [c['name'] for c in inspector.get_columns('characters')]
    if 'basic_info' in char_columns:
        op.drop_column('characters', 'basic_info')
    if 'tags' in char_columns:
        op.drop_column('characters', 'tags')
