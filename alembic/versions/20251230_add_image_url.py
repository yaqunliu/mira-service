"""add_image_url_to_shots_and_scenes

Revision ID: 20251230_add_image_url
Revises: 626514ef1203
Create Date: 2025-12-30 17:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20251230_add_image_url'
down_revision = '626514ef1203'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Add image_url column to shots if it doesn't exist
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    if 'image_url' not in shot_columns:
        op.add_column('shots', sa.Column('image_url', sa.String(length=500), nullable=True))
        print("Added image_url column to shots table")
    else:
        print("image_url column already exists in shots table")
        
    # Add image_url column to scenes if it doesn't exist
    scene_columns = [c['name'] for c in inspector.get_columns('scenes')]
    if 'image_url' not in scene_columns:
        op.add_column('scenes', sa.Column('image_url', sa.String(length=500), nullable=True))
        print("Added image_url column to scenes table")
    else:
        print("image_url column already exists in scenes table")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Remove image_url column from shots if it exists
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    if 'image_url' in shot_columns:
        op.drop_column('shots', 'image_url')
        
    # Remove image_url column from scenes if it exists
    scene_columns = [c['name'] for c in inspector.get_columns('scenes')]
    if 'image_url' in scene_columns:
        op.drop_column('scenes', 'image_url')
