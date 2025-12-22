"""Add missing subscription fields

Revision ID: add_subscription_fields_001
Revises: merge_payment_character_001
Create Date: 2025-01-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'add_subscription_fields_001'
down_revision = 'merge_payment_character_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 检查列是否已存在
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('subscriptions')]
    
    # 添加 next_billing_date 字段（如果不存在）
    if 'next_billing_date' not in columns:
        op.add_column('subscriptions', sa.Column('next_billing_date', sa.DateTime(timezone=True), nullable=True))
    
    # 添加 points_per_period 字段（如果不存在）
    if 'points_per_period' not in columns:
        # 检查是否有旧的 points_amount 字段
        if 'points_amount' in columns:
            # 迁移数据：将 points_amount 的值复制到 points_per_period
            op.add_column('subscriptions', sa.Column('points_per_period', sa.Integer(), nullable=True))
            op.execute("UPDATE subscriptions SET points_per_period = points_amount WHERE points_per_period IS NULL")
            # 设置为 NOT NULL
            op.alter_column('subscriptions', 'points_per_period', nullable=False)
        else:
            op.add_column('subscriptions', sa.Column('points_per_period', sa.Integer(), nullable=False))
    
    # 添加 last_points_issued_at 字段（如果不存在）
    if 'last_points_issued_at' not in columns:
        op.add_column('subscriptions', sa.Column('last_points_issued_at', sa.DateTime(timezone=True), nullable=True))
    
    # 删除旧的 points_amount 字段（如果存在且 points_per_period 已创建）
    columns_after = [col['name'] for col in inspector.get_columns('subscriptions')]
    if 'points_amount' in columns_after and 'points_per_period' in columns_after:
        try:
            op.drop_column('subscriptions', 'points_amount')
        except:
            pass  # 如果删除失败，忽略（可能被其他地方引用）


def downgrade() -> None:
    # 删除新字段
    op.drop_column('subscriptions', 'last_points_issued_at')
    op.drop_column('subscriptions', 'points_per_period')
    op.drop_column('subscriptions', 'next_billing_date')

