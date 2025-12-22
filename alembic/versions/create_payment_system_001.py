"""Create unified payment system - initial migration

Revision ID: payment_system_001
Revises: merge_uuid_supabase_temp
Create Date: 2025-01-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'payment_system_001'
down_revision = 'merge_uuid_supabase_temp'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 创建产品表（products）
    op.create_table(
        'products',
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('payment_method', sa.String(length=20), nullable=False),  # creem, wechat
        sa.Column('language', sa.String(length=10), nullable=False),  # zh, en, ja等
        sa.Column('origin_product_id', sa.String(length=100), nullable=True),  # 远程产品ID（用于购买对应的远程产品）
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Integer(), nullable=False),  # 金额(分)
        sa.Column('currency', sa.String(length=10), nullable=False),  # USD, CNY
        sa.Column('billing_type', sa.String(length=20), nullable=False),  # onetime, recurring
        sa.Column('billing_period', sa.String(length=50), nullable=True),  # monthly, yearly等
        sa.Column('points_amount', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),  # active, inactive
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('product_url', sa.String(length=500), nullable=True),
        sa.Column('features', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('product_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('product_id'),
        sa.UniqueConstraint('uuid'),
    )
    op.create_index(op.f('ix_products_product_id'), 'products', ['product_id'], unique=False)
    op.create_index(op.f('ix_products_uuid'), 'products', ['uuid'], unique=True)
    op.create_index(op.f('ix_products_payment_method'), 'products', ['payment_method'], unique=False)
    op.create_index(op.f('ix_products_language'), 'products', ['language'], unique=False)
    op.create_index(op.f('ix_products_currency'), 'products', ['currency'], unique=False)
    op.create_index(op.f('ix_products_origin_product_id'), 'products', ['origin_product_id'], unique=False)
    op.create_index(op.f('ix_products_billing_type'), 'products', ['billing_type'], unique=False)
    op.create_index(op.f('ix_products_status'), 'products', ['status'], unique=False)
    
    # 2. 创建订单表（orders）
    op.create_table(
        'orders',
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('order_number', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('payment_method', sa.String(length=20), nullable=False),  # creem, wechat
        sa.Column('order_type', sa.String(length=20), nullable=False),  # onetime, subscription
        sa.Column('status', sa.String(length=20), nullable=False),  # pending, paid, failed, cancelled, refunded
        sa.Column('amount', sa.Integer(), nullable=False),  # 金额(分)
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='USD'),
        sa.Column('points_amount', sa.Integer(), nullable=False),
        sa.Column('points_issued', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('success_url', sa.String(length=500), nullable=True),
        sa.Column('cancel_url', sa.String(length=500), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('order_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.product_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('order_id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('order_number'),
    )
    op.create_index(op.f('ix_orders_order_id'), 'orders', ['order_id'], unique=False)
    op.create_index(op.f('ix_orders_uuid'), 'orders', ['uuid'], unique=True)
    op.create_index(op.f('ix_orders_order_number'), 'orders', ['order_number'], unique=True)
    op.create_index(op.f('ix_orders_user_id'), 'orders', ['user_id'], unique=False)
    op.create_index(op.f('ix_orders_product_id'), 'orders', ['product_id'], unique=False)
    op.create_index(op.f('ix_orders_payment_method'), 'orders', ['payment_method'], unique=False)
    op.create_index(op.f('ix_orders_order_type'), 'orders', ['order_type'], unique=False)
    op.create_index(op.f('ix_orders_status'), 'orders', ['status'], unique=False)
    
    # 3. 创建Creem支付详情表
    op.create_table(
        'creem_payments',
        sa.Column('payment_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('creem_checkout_id', sa.String(length=100), nullable=True),
        sa.Column('creem_transaction_id', sa.String(length=100), nullable=True),
        sa.Column('checkout_url', sa.String(length=500), nullable=True),
        sa.Column('payment_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('payment_id'),
        sa.UniqueConstraint('order_id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('creem_checkout_id'),
    )
    op.create_index(op.f('ix_creem_payments_payment_id'), 'creem_payments', ['payment_id'], unique=False)
    op.create_index(op.f('ix_creem_payments_uuid'), 'creem_payments', ['uuid'], unique=True)
    op.create_index(op.f('ix_creem_payments_order_id'), 'creem_payments', ['order_id'], unique=False)
    op.create_index(op.f('ix_creem_payments_creem_checkout_id'), 'creem_payments', ['creem_checkout_id'], unique=True)
    
    # 4. 创建微信支付详情表
    op.create_table(
        'wechat_payments',
        sa.Column('payment_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('wechat_transaction_id', sa.String(length=100), nullable=True),
        sa.Column('out_trade_no', sa.String(length=100), nullable=False),
        sa.Column('code_url', sa.String(length=500), nullable=True),
        sa.Column('prepay_id', sa.String(length=100), nullable=True),
        sa.Column('payment_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('payment_id'),
        sa.UniqueConstraint('order_id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('out_trade_no'),
    )
    op.create_index(op.f('ix_wechat_payments_payment_id'), 'wechat_payments', ['payment_id'], unique=False)
    op.create_index(op.f('ix_wechat_payments_uuid'), 'wechat_payments', ['uuid'], unique=True)
    op.create_index(op.f('ix_wechat_payments_order_id'), 'wechat_payments', ['order_id'], unique=False)
    op.create_index(op.f('ix_wechat_payments_wechat_transaction_id'), 'wechat_payments', ['wechat_transaction_id'], unique=False)
    op.create_index(op.f('ix_wechat_payments_out_trade_no'), 'wechat_payments', ['out_trade_no'], unique=True)
    
    # 5. 创建订阅表（subscriptions）
    op.create_table(
        'subscriptions',
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('payment_method', sa.String(length=20), nullable=False),  # creem, wechat
        sa.Column('status', sa.String(length=20), nullable=False),  # active, cancelled, expired, paused
        sa.Column('billing_period', sa.String(length=50), nullable=False),  # every-month, every-year等
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_billing_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('points_per_period', sa.Integer(), nullable=False),
        sa.Column('last_points_issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('subscription_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.product_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('subscription_id'),
        sa.UniqueConstraint('uuid'),
    )
    op.create_index(op.f('ix_subscriptions_subscription_id'), 'subscriptions', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_uuid'), 'subscriptions', ['uuid'], unique=True)
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_product_id'), 'subscriptions', ['product_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_order_id'), 'subscriptions', ['order_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_payment_method'), 'subscriptions', ['payment_method'], unique=False)
    op.create_index(op.f('ix_subscriptions_status'), 'subscriptions', ['status'], unique=False)
    
    # 6. 创建Creem订阅详情表
    op.create_table(
        'creem_subscriptions',
        sa.Column('subscription_detail_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('creem_subscription_id', sa.String(length=100), nullable=False),
        sa.Column('subscription_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.subscription_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('subscription_detail_id'),
        sa.UniqueConstraint('subscription_id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('creem_subscription_id'),
    )
    op.create_index(op.f('ix_creem_subscriptions_subscription_detail_id'), 'creem_subscriptions', ['subscription_detail_id'], unique=False)
    op.create_index(op.f('ix_creem_subscriptions_uuid'), 'creem_subscriptions', ['uuid'], unique=True)
    op.create_index(op.f('ix_creem_subscriptions_subscription_id'), 'creem_subscriptions', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_creem_subscriptions_creem_subscription_id'), 'creem_subscriptions', ['creem_subscription_id'], unique=True)
    
    # 7. 创建微信订阅详情表
    op.create_table(
        'wechat_subscriptions',
        sa.Column('subscription_detail_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('wechat_contract_id', sa.String(length=100), nullable=True),
        sa.Column('wechat_plan_id', sa.Integer(), nullable=True),
        sa.Column('wechat_request_serial', sa.BigInteger(), nullable=True),
        sa.Column('subscription_metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.subscription_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('subscription_detail_id'),
        sa.UniqueConstraint('subscription_id'),
        sa.UniqueConstraint('uuid'),
        sa.UniqueConstraint('wechat_contract_id'),
    )
    op.create_index(op.f('ix_wechat_subscriptions_subscription_detail_id'), 'wechat_subscriptions', ['subscription_detail_id'], unique=False)
    op.create_index(op.f('ix_wechat_subscriptions_uuid'), 'wechat_subscriptions', ['uuid'], unique=True)
    op.create_index(op.f('ix_wechat_subscriptions_subscription_id'), 'wechat_subscriptions', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_wechat_subscriptions_wechat_contract_id'), 'wechat_subscriptions', ['wechat_contract_id'], unique=True)
    
    # 8. 创建订阅积分历史表（subscription_points_history）
    op.create_table(
        'subscription_points_history',
        sa.Column('history_id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('payment_method', sa.String(length=20), nullable=False),  # creem, wechat
        sa.Column('invoice_id', sa.String(length=100), nullable=True),  # 通用发票ID
        sa.Column('points_amount', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.subscription_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('history_id'),
        sa.UniqueConstraint('subscription_id', 'period_start', name='uq_subscription_points_history_subscription_period'),
    )
    op.create_index(op.f('ix_subscription_points_history_history_id'), 'subscription_points_history', ['history_id'], unique=False)
    op.create_index(op.f('ix_subscription_points_history_subscription_id'), 'subscription_points_history', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_subscription_points_history_payment_method'), 'subscription_points_history', ['payment_method'], unique=False)
    op.create_index(op.f('ix_subscription_points_history_invoice_id'), 'subscription_points_history', ['invoice_id'], unique=False)
    
    # 9. 更新webhook_events表，添加source字段
    op.add_column(
        'webhook_events',
        sa.Column('source', sa.String(length=20), nullable=True, server_default='webhook')
    )
    op.execute("UPDATE webhook_events SET source = 'webhook' WHERE source IS NULL")
    op.create_index(
        op.f('ix_webhook_events_source'),
        'webhook_events',
        ['source'],
        unique=False
    )


def downgrade() -> None:
    # 删除webhook_events的source字段
    op.drop_index(op.f('ix_webhook_events_source'), table_name='webhook_events')
    op.drop_column('webhook_events', 'source')
    
    # 删除订阅积分历史表
    op.drop_table('subscription_points_history')
    
    # 删除订阅详情表
    op.drop_table('wechat_subscriptions')
    op.drop_table('creem_subscriptions')
    
    # 删除订阅表
    op.drop_table('subscriptions')
    
    # 删除支付详情表
    op.drop_table('wechat_payments')
    op.drop_table('creem_payments')
    
    # 删除订单表
    op.drop_table('orders')
    
    # 删除产品表
    op.drop_table('products')

