"""add_status_fields

Revision ID: 20251230_add_status_fields
Revises: 20251230_add_v2_fields
Create Date: 2025-12-30 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20251230_add_status_fields'
down_revision = '20251230_add_v2_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Check and add for characters
    # Use lowercase for table names as they are usually lowercase in Postgres
    char_columns = [c['name'] for c in inspector.get_columns('characters')]
    if 'status_detail' not in char_columns:
        op.add_column('characters', sa.Column('status_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        
    # Check and add for scenes
    scene_columns = [c['name'] for c in inspector.get_columns('scenes')]
    if 'status' not in scene_columns:
        op.add_column('scenes', sa.Column('status', sa.String(length=20), server_default='pending', nullable=True))
    if 'status_detail' not in scene_columns:
        op.add_column('scenes', sa.Column('status_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # Check and add for shots
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    if 'status_detail' not in shot_columns:
        op.add_column('shots', sa.Column('status_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Remove added columns if they exist
    char_columns = [c['name'] for c in inspector.get_columns('characters')]
    if 'status_detail' in char_columns:
        op.drop_column('characters', 'status_detail')
        
    scene_columns = [c['name'] for c in inspector.get_columns('scenes')]
    if 'status' in scene_columns:
        op.drop_column('scenes', 'status')
    if 'status_detail' in scene_columns:
        op.drop_column('scenes', 'status_detail')
        
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    if 'status_detail' in shot_columns:
        op.drop_column('shots', 'status_detail')
