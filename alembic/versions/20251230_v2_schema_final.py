"""v2_schema_final

Revision ID: 20251230_v2_schema_final
Revises: 20251230_cleanup_v2_fields
Create Date: 2025-12-30 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20251230_v2_schema_final'
down_revision = '20251230_cleanup_v2_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # 1. SCENES Table
    scene_columns = [c['name'] for c in inspector.get_columns('scenes')]
    
    # Restoring status_detail if missing
    if 'status_detail' not in scene_columns:
        op.add_column('scenes', sa.Column('status_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        
    # Adding extra_data for V2 properties
    if 'extra_data' not in scene_columns:
        op.add_column('scenes', sa.Column('extra_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        
    # Removing specific V2 columns (environment_setting, scene_graph_prompt, etc.) in favor of extra_data
    fields_to_drop_scenes = [
        'environment_setting', 'scene_graph_prompt', 'scene_graph_url', 
        'lighting_info', 'environment_details', 'environment_images'
    ]
    for field in fields_to_drop_scenes:
        if field in scene_columns:
            op.drop_column('scenes', field)


    # 2. SHOTS Table
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    
    # Restoring status_detail if missing
    if 'status_detail' not in shot_columns:
        op.add_column('shots', sa.Column('status_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        
    # Adding extra_data for V2 properties
    if 'extra_data' not in shot_columns:
        op.add_column('shots', sa.Column('extra_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        
    # Removing specific V2 columns in favor of extra_data
    fields_to_drop_shots = [
        'video_prompt', 'script_content', 'camera_movement', 
        'dialogue_info', 'character_actions', 'frame_composition', 
        'onscreen_characters', 'voice_characters', 
        'audio_strategy', 'audio_evaluation'
    ]
    for field in fields_to_drop_shots:
        if field in shot_columns:
            op.drop_column('shots', field)
            

    # 3. CHARACTERS Table
    char_columns = [c['name'] for c in inspector.get_columns('characters')]
    
    # Restoring status_detail if missing
    if 'status_detail' not in char_columns:
        op.add_column('characters', sa.Column('status_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    # Downgrade logic skipped for this dev iteration to avoid complexity in restoring specific columns
    op.drop_column('scenes', 'extra_data')
    op.drop_column('shots', 'extra_data')
