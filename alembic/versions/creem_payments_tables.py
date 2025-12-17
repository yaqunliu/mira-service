"""Add Creem payment tables

Revision ID: creem_payments_001
Revises: merge_uuid_supabase_temp
Create Date: 2025-12-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'creem_payments_001'
down_revision = 'merge_uuid_supabase_temp'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # products
    op.create_table(
        'products',
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('creem_product_id', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='USD'),
        sa.Column('billing_type', sa.String(length=20), nullable=False),
        sa.Column('billing_period', sa.String(length=50), nullable=True),
        sa.Column('points_amount', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('image_url', sa.String(length=500), nullable=True),
        sa.Column('product_url', sa.String(length=500), nullable=True),
        sa.Column('features', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('creem_mode', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('product_id'),
        sa.UniqueConstraint('creem_product_id'),
    )
    op.create_index(op.f('ix_products_product_id'), 'products', ['product_id'], unique=False)
    op.create_index(op.f('ix_products_uuid'), 'products', ['uuid'], unique=True)
    op.create_index(op.f('ix_products_status'), 'products', ['status'], unique=False)
    op.create_index(op.f('ix_products_billing_type'), 'products', ['billing_type'], unique=False)

    # orders
    op.create_table(
        'orders',
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('order_number', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('creem_checkout_id', sa.String(length=100), nullable=True),
        sa.Column('creem_transaction_id', sa.String(length=100), nullable=True),
        sa.Column('order_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False, server_default='USD'),
        sa.Column('points_amount', sa.Integer(), nullable=False),
        sa.Column('points_issued', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('checkout_url', sa.String(length=500), nullable=True),
        sa.Column('success_url', sa.String(length=500), nullable=True),
        sa.Column('cancel_url', sa.String(length=500), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['product_id'], ['products.product_id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
        sa.PrimaryKeyConstraint('order_id'),
        sa.UniqueConstraint('order_number'),
    )
    op.create_index(op.f('ix_orders_order_id'), 'orders', ['order_id'], unique=False)
    op.create_index(op.f('ix_orders_uuid'), 'orders', ['uuid'], unique=True)
    op.create_index(op.f('ix_orders_user_id'), 'orders', ['user_id'], unique=False)
    op.create_index(op.f('ix_orders_product_id'), 'orders', ['product_id'], unique=False)
    op.create_index(op.f('ix_orders_status'), 'orders', ['status'], unique=False)
    op.create_index(op.f('ix_orders_order_type'), 'orders', ['order_type'], unique=False)
    op.create_index(op.f('ix_orders_creem_checkout_id'), 'orders', ['creem_checkout_id'], unique=True)

    # subscriptions
    op.create_table(
        'subscriptions',
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('creem_subscription_id', sa.String(length=100), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('billing_period', sa.String(length=50), nullable=False),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_billing_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('points_per_period', sa.Integer(), nullable=False),
        sa.Column('last_points_issued_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=True, server_default=sa.text('false')),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
        sa.PrimaryKeyConstraint('subscription_id'),
        sa.UniqueConstraint('order_id'),
        sa.UniqueConstraint('creem_subscription_id'),
    )
    op.create_index(op.f('ix_subscriptions_subscription_id'), 'subscriptions', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_uuid'), 'subscriptions', ['uuid'], unique=True)
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_status'), 'subscriptions', ['status'], unique=False)
    op.create_index(op.f('ix_subscriptions_billing_period'), 'subscriptions', ['billing_period'], unique=False)

    # subscription_points_history
    op.create_table(
        'subscription_points_history',
        sa.Column('history_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('points_record_id', sa.Integer(), nullable=True),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('points_amount', sa.Integer(), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('creem_invoice_id', sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(['order_id'], ['orders.order_id'], ),
        sa.ForeignKeyConstraint(['points_record_id'], ['points_records.record_id'], ),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.subscription_id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
        sa.PrimaryKeyConstraint('history_id'),
    )
    op.create_index(op.f('ix_subscription_points_history_history_id'), 'subscription_points_history', ['history_id'], unique=False)
    op.create_index(op.f('ix_subscription_points_history_uuid'), 'subscription_points_history', ['uuid'], unique=True)
    op.create_index(op.f('ix_subscription_points_history_subscription_id'), 'subscription_points_history', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_subscription_points_history_order_id'), 'subscription_points_history', ['order_id'], unique=False)
    op.create_index(op.f('ix_subscription_points_history_user_id'), 'subscription_points_history', ['user_id'], unique=False)
    op.create_index(op.f('ix_subscription_points_history_period_start'), 'subscription_points_history', ['period_start'], unique=False)

    # webhook_events
    op.create_table(
        'webhook_events',
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('creem_event_id', sa.String(length=100), nullable=True),
        sa.Column('payload', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('processed', sa.Boolean(), nullable=True, server_default=sa.text('false')),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('event_id'),
        sa.UniqueConstraint('creem_event_id'),
    )
    op.create_index(op.f('ix_webhook_events_event_id'), 'webhook_events', ['event_id'], unique=False)
    op.create_index(op.f('ix_webhook_events_uuid'), 'webhook_events', ['uuid'], unique=True)
    op.create_index(op.f('ix_webhook_events_event_type'), 'webhook_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_webhook_events_processed'), 'webhook_events', ['processed'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_webhook_events_processed'), table_name='webhook_events')
    op.drop_index(op.f('ix_webhook_events_event_type'), table_name='webhook_events')
    op.drop_index(op.f('ix_webhook_events_uuid'), table_name='webhook_events')
    op.drop_index(op.f('ix_webhook_events_event_id'), table_name='webhook_events')
    op.drop_table('webhook_events')

    op.drop_index(op.f('ix_subscription_points_history_period_start'), table_name='subscription_points_history')
    op.drop_index(op.f('ix_subscription_points_history_user_id'), table_name='subscription_points_history')
    op.drop_index(op.f('ix_subscription_points_history_order_id'), table_name='subscription_points_history')
    op.drop_index(op.f('ix_subscription_points_history_subscription_id'), table_name='subscription_points_history')
    op.drop_index(op.f('ix_subscription_points_history_uuid'), table_name='subscription_points_history')
    op.drop_index(op.f('ix_subscription_points_history_history_id'), table_name='subscription_points_history')
    op.drop_table('subscription_points_history')

    op.drop_index(op.f('ix_subscriptions_billing_period'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_status'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_user_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_uuid'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_subscription_id'), table_name='subscriptions')
    op.drop_table('subscriptions')

    op.drop_index(op.f('ix_orders_creem_checkout_id'), table_name='orders')
    op.drop_index(op.f('ix_orders_order_type'), table_name='orders')
    op.drop_index(op.f('ix_orders_status'), table_name='orders')
    op.drop_index(op.f('ix_orders_product_id'), table_name='orders')
    op.drop_index(op.f('ix_orders_user_id'), table_name='orders')
    op.drop_index(op.f('ix_orders_uuid'), table_name='orders')
    op.drop_index(op.f('ix_orders_order_id'), table_name='orders')
    op.drop_table('orders')

    op.drop_index(op.f('ix_products_billing_type'), table_name='products')
    op.drop_index(op.f('ix_products_status'), table_name='products')
    op.drop_index(op.f('ix_products_uuid'), table_name='products')
    op.drop_index(op.f('ix_products_product_id'), table_name='products')
    op.drop_table('products')

