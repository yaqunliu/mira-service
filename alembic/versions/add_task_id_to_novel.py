"""add task_id to novel

Revision ID: add_task_id_to_novel
Revises: 11bfa86eb501
Create Date: 2025-11-07 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_task_id_to_novel'
down_revision = '11bfa86eb501'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 task_id 字段到 novels 表
    op.add_column('novels', sa.Column('task_id', sa.String(length=100), nullable=True))
    # 创建索引以提高查询性能
    op.create_index(op.f('ix_novels_task_id'), 'novels', ['task_id'], unique=False)


def downgrade() -> None:
    # 删除索引
    op.drop_index(op.f('ix_novels_task_id'), table_name='novels')
    # 删除 task_id 字段
    op.drop_column('novels', 'task_id')

