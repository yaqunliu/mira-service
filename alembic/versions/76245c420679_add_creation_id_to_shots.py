"""add_creation_id_to_shots

Revision ID: 76245c420679
Revises: 002
Create Date: 2026-01-30 11:08:02.352991

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '76245c420679'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 creation_id 列到 shots 表
    op.add_column('shots', sa.Column('creation_id', sa.Integer(), nullable=True))
    # 添加外键约束
    op.create_foreign_key(
        'fk_shots_creation_id',
        'shots', 'creations',
        ['creation_id'], ['creation_id']
    )
    # 创建索引
    op.create_index('ix_shots_creation_id', 'shots', ['creation_id'])


def downgrade() -> None:
    # 删除索引
    op.drop_index('ix_shots_creation_id', table_name='shots')
    # 删除外键约束
    op.drop_constraint('fk_shots_creation_id', 'shots', type_='foreignkey')
    # 删除列
    op.drop_column('shots', 'creation_id')
