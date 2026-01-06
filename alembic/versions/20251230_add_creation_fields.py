"""add_creation_fields

Revision ID: 20251230_add_creation_fields
Revises: 20251230_add_novel_type
Create Date: 2025-12-30 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251230_add_creation_fields'
down_revision = '20251230_add_novel_type'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add creation_type column to creations table
    op.add_column('creations', sa.Column('creation_type', sa.String(length=20), server_default='chapter', nullable=False))
    
    # Add preview_text column
    op.add_column('creations', sa.Column('preview_text', sa.String(length=500), nullable=True))
    
    # Add text_content_url column
    op.add_column('creations', sa.Column('text_content_url', sa.String(length=500), nullable=True))


def downgrade() -> None:
    # Remove added columns
    op.drop_column('creations', 'creation_type')
    op.drop_column('creations', 'preview_text')
    op.drop_column('creations', 'text_content_url')
