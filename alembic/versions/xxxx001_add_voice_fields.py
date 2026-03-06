"""Add voice_id and voice_speed to characters

Revision ID: xxxx001_add_voice_fields
Revises: 002
Create Date: 2026-01-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'xxxx001_add_voice_fields'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 voice_id 列到 characters 表
    op.add_column('characters', sa.Column('voice_id', sa.String(length=100), nullable=True))
    
    # 添加 voice_speed 列到 characters 表
    op.add_column('characters', sa.Column('voice_speed', sa.String(length=20), nullable=True, server_default='1.0'))


def downgrade() -> None:
    # 删除 voice_speed 列
    op.drop_column('characters', 'voice_speed')
    
    # 删除 voice_id 列
    op.drop_column('characters', 'voice_id')
