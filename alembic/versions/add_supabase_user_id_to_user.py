"""Add supabase_user_id to user

Revision ID: add_supabase_user_id
Revises: f5g6h7i8j9k0
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_supabase_user_id'
down_revision = 'f5g6h7i8j9k0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 supabase_user_id 字段
    op.add_column('users', sa.Column('supabase_user_id', sa.String(length=255), nullable=True))
    
    # 创建 supabase_user_id 的唯一索引
    op.create_index(op.f('ix_users_supabase_user_id'), 'users', ['supabase_user_id'], unique=True)
    
    # 将 hashed_password 改为可选（允许 NULL）
    # 注意：PostgreSQL 中，如果列已经有 NOT NULL 约束，需要先删除约束
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(length=255),
                    nullable=True)


def downgrade() -> None:
    # 删除索引
    op.drop_index(op.f('ix_users_supabase_user_id'), table_name='users')
    
    # 删除 supabase_user_id 字段
    op.drop_column('users', 'supabase_user_id')
    
    # 恢复 hashed_password 为必填（注意：这可能会导致数据问题，如果已有 NULL 值）
    # 在实际降级时，需要先处理 NULL 值
    op.alter_column('users', 'hashed_password',
                    existing_type=sa.String(length=255),
                    nullable=False)

