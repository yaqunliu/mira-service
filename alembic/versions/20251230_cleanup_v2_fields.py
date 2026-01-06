"""cleanup_v2_fields

Revision ID: 20251230_cleanup_v2_fields
Revises: 20251230_add_missing_v2_columns_safe
Create Date: 2025-12-30 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20251230_cleanup_v2_fields'
down_revision = '20251230_add_v2_safe'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # 1. Clean Creations Table
    creation_columns = [c['name'] for c in inspector.get_columns('creations')]
    if 'character_feature_library_url' in creation_columns:
        op.drop_column('creations', 'character_feature_library_url')
    if 'character_feature_library' in creation_columns:
        op.drop_column('creations', 'character_feature_library')
        
    # 2. Clean Scenes Table
    scene_columns = [c['name'] for c in inspector.get_columns('scenes')]
    if 'environment_images' in scene_columns:
        op.drop_column('scenes', 'environment_images')
        
    # 3. Clean Shots Table
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    if 'audio_strategy' in shot_columns:
        op.drop_column('shots', 'audio_strategy')
    if 'audio_evaluation' in shot_columns:
        op.drop_column('shots', 'audio_evaluation')


def downgrade() -> None:
    # Re-add removed columns
    # Creations
    op.add_column('creations', sa.Column('character_feature_library_url', sa.String(length=500), nullable=True))
    op.add_column('creations', sa.Column('character_feature_library', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    
    # Scenes
    op.add_column('scenes', sa.Column('environment_images', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    
    # Shots
    op.add_column('shots', sa.Column('audio_strategy', sa.String(length=20), nullable=True))
    op.add_column('shots', sa.Column('audio_evaluation', sa.String(length=20), nullable=True))
