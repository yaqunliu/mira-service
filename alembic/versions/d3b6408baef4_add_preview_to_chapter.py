"""add_preview_to_chapter

Revision ID: d3b6408baef4
Revises: add_task_id_to_novel
Create Date: 2025-11-10 18:53:02.551337

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3b6408baef4'
down_revision = 'add_task_id_to_novel'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 preview 字段到 chapters 表
    op.add_column('chapters', sa.Column('preview', sa.String(length=100), nullable=True))


def downgrade() -> None:
    # 删除 preview 字段
    op.drop_column('chapters', 'preview')
