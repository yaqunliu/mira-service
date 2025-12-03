"""add deleted_at to chapters and creations

Revision ID: add_deleted_at_001
Revises: e4f5g6h7i8j9
Create Date: 2025-12-02 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_deleted_at_001'
down_revision = 'add_temp_points'  # 合并到积分系统迁移之后
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 为 chapters 表添加 deleted_at 字段
    op.add_column('chapters', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_chapters_deleted_at'), 'chapters', ['deleted_at'], unique=False)
    
    # 为 creations 表添加 deleted_at 字段
    op.add_column('creations', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f('ix_creations_deleted_at'), 'creations', ['deleted_at'], unique=False)


def downgrade() -> None:
    # 删除索引
    op.drop_index(op.f('ix_creations_deleted_at'), table_name='creations')
    op.drop_index(op.f('ix_chapters_deleted_at'), table_name='chapters')
    
    # 删除字段
    op.drop_column('creations', 'deleted_at')
    op.drop_column('chapters', 'deleted_at')
