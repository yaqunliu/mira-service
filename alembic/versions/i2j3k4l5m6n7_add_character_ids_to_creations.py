"""Add character_ids to creations

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2025-12-09 11:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'i2j3k4l5m6n7'
down_revision = 'h1i2j3k4l5m6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 为 creations 表添加 character_ids 字段（JSONB类型，存储角色ID列表）
    op.add_column('creations', 
        sa.Column('character_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    # 删除 character_ids 字段
    op.drop_column('creations', 'character_ids')

