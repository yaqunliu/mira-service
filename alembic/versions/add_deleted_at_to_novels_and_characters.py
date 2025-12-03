"""add deleted_at to novels and characters

Revision ID: add_deleted_at_002
Revises: add_deleted_at_001
Create Date: 2025-12-03 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_deleted_at_002'
down_revision = 'add_deleted_at_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 为 novels 表添加 deleted_at 字段
    op.add_column('novels', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_novels_deleted_at'), 'novels', ['deleted_at'], unique=False)
    
    # 为 characters 表添加 deleted_at 字段
    op.add_column('characters', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_characters_deleted_at'), 'characters', ['deleted_at'], unique=False)


def downgrade() -> None:
    # 删除索引
    op.drop_index(op.f('ix_characters_deleted_at'), table_name='characters')
    op.drop_index(op.f('ix_novels_deleted_at'), table_name='novels')
    
    # 删除字段
    op.drop_column('characters', 'deleted_at')
    op.drop_column('novels', 'deleted_at')
