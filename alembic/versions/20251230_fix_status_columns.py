"""add_missing_status_columns

Revision ID: 20251230_fix_status_columns
Revises: 20251230_add_status_fields
Create Date: 2025-12-30 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20251230_fix_status_columns'
down_revision = '20251230_add_status_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Add status column to characters if it doesn't exist
    char_columns = [c['name'] for c in inspector.get_columns('characters')]
    if 'status' not in char_columns:
        op.add_column('characters', sa.Column('status', sa.String(length=20), server_default='pending', nullable=True))
        print("Added status column to characters table")
    else:
        print("Status column already exists in characters table")
        
    # Add status column to shots if it doesn't exist
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    if 'status' not in shot_columns:
        op.add_column('shots', sa.Column('status', sa.String(length=20), server_default='pending', nullable=True))
        print("Added status column to shots table")
    else:
        print("Status column already exists in shots table")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    
    # Remove status column from characters if it exists
    char_columns = [c['name'] for c in inspector.get_columns('characters')]
    if 'status' in char_columns:
        op.drop_column('characters', 'status')
        
    # Remove status column from shots if it exists
    shot_columns = [c['name'] for c in inspector.get_columns('shots')]
    if 'status' in shot_columns:
        op.drop_column('shots', 'status')
