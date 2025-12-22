"""Merge payment system and character_ids migrations

Revision ID: merge_payment_character_001
Revises: ('payment_system_001', 'i2j3k4l5m6n7')
Create Date: 2025-01-20
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'merge_payment_character_001'
down_revision = ('payment_system_001', 'i2j3k4l5m6n7')
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 这是一个合并迁移，不需要执行任何操作
    # 两个分支已经各自完成了自己的迁移
    pass


def downgrade() -> None:
    # 合并迁移的降级也不需要操作
    pass

