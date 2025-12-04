"""Merge uuid and avatar migrations

Revision ID: merge_uuid_supabase_temp
Revises: 8f1780b73480, add_avatar_to_user
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'merge_uuid_supabase_temp'
down_revision = ('8f1780b73480', 'add_avatar_to_user')
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 这是一个合并迁移，不需要执行任何操作
    # 它只是将两个分支合并到一起：
    # - 8f1780b73480: uuid迁移
    # - add_avatar_to_user: 添加avatar字段的迁移（依赖于c190ee2e8107，已合并supabase和deleted_at）
    pass


def downgrade() -> None:
    # 这是一个合并迁移，不需要执行任何操作
    pass
