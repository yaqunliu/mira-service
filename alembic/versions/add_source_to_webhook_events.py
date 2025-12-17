"""Add source field to webhook_events

Revision ID: add_source_webhook
Revises: 5919d061f98c
Create Date: 2025-01-20
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_source_webhook'
down_revision = '5919d061f98c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 添加 source 字段到 webhook_events 表
    op.add_column(
        'webhook_events',
        sa.Column('source', sa.String(length=20), nullable=True, server_default='webhook')
    )
    # 为现有记录设置默认值
    op.execute("UPDATE webhook_events SET source = 'webhook' WHERE source IS NULL")
    # 创建索引
    op.create_index(
        op.f('ix_webhook_events_source'),
        'webhook_events',
        ['source'],
        unique=False
    )


def downgrade() -> None:
    # 删除索引
    op.drop_index(op.f('ix_webhook_events_source'), table_name='webhook_events')
    # 删除 source 字段
    op.drop_column('webhook_events', 'source')

