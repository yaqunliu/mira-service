"""Add avatar to user

Revision ID: add_avatar_to_user
Revises: c190ee2e8107
Create Date: 2025-12-04 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_avatar_to_user'
down_revision = 'c190ee2e8107'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 avatar 字段到 users 表
    op.add_column('users', sa.Column('avatar', sa.String(length=500), nullable=True))


def downgrade() -> None:
    # 删除 avatar 字段
    op.drop_column('users', 'avatar')

