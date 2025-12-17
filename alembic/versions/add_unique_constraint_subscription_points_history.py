"""Add unique constraint to subscription_points_history

Revision ID: add_unique_subscription_history
Revises: add_source_webhook
Create Date: 2025-01-20
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_unique_subscription_history'
down_revision = 'add_source_webhook'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加唯一约束：subscription_id + period_start 组合唯一
    # 防止 webhook 和轮询同时发放导致重复
    op.create_unique_constraint(
        'uq_subscription_points_history_subscription_period',
        'subscription_points_history',
        ['subscription_id', 'period_start']
    )


def downgrade() -> None:
    # 删除唯一约束
    op.drop_constraint(
        'uq_subscription_points_history_subscription_period',
        'subscription_points_history',
        type_='unique'
    )

