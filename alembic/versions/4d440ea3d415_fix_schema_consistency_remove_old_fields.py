"""fix_schema_consistency_remove_old_fields

Revision ID: 4d440ea3d415
Revises: rename_product_id_fields_001
Create Date: 2025-12-19 17:40:00.000000

修复数据库表结构和 SQLAlchemy 模型的一致性：
1. 删除 products.synced_at（旧字段）
2. 删除 subscriptions.points_amount（已用 points_per_period 替代）
3. 修复 subscriptions.cancel_at_period_end 的可空性
4. 为 subscription_points_history 添加缺失的字段（uuid, user_id, order_id, points_record_id, creem_invoice_id）
5. 修复 subscription_points_history.payment_method 的可空性
6. 确保 subscription_points_history.created_at 存在

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '4d440ea3d415'
down_revision = 'rename_product_id_fields_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """修复数据库表结构和模型的一致性"""
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # ========== 1. products 表：删除 synced_at 字段 ==========
    columns = [col['name'] for col in inspector.get_columns('products')]
    if 'synced_at' in columns:
        try:
            op.drop_column('products', 'synced_at')
        except Exception as e:
            # 如果删除失败，可能是字段不存在或已被删除
            pass
    
    # ========== 2. subscriptions 表：删除 points_amount 字段 ==========
    columns = [col['name'] for col in inspector.get_columns('subscriptions')]
    if 'points_amount' in columns:
        try:
            # 确保 points_per_period 存在且有数据
            op.execute("""
                UPDATE subscriptions 
                SET points_per_period = points_amount 
                WHERE points_per_period IS NULL OR points_per_period = 0
            """)
            op.drop_column('subscriptions', 'points_amount')
        except Exception as e:
            # 如果删除失败，可能是字段不存在或已被删除
            pass
    
    # ========== 3. subscriptions 表：修复 cancel_at_period_end 的可空性 ==========
    columns = [col['name'] for col in inspector.get_columns('subscriptions')]
    if 'cancel_at_period_end' in columns:
        # 检查当前的可空性
        cancel_col = next((col for col in inspector.get_columns('subscriptions') if col['name'] == 'cancel_at_period_end'), None)
        if cancel_col and cancel_col['nullable']:
            # 先设置默认值
            op.execute("UPDATE subscriptions SET cancel_at_period_end = false WHERE cancel_at_period_end IS NULL")
            # 然后修改为 NOT NULL
            op.alter_column('subscriptions', 'cancel_at_period_end',
                          existing_type=sa.Boolean(),
                          nullable=False,
                          server_default=sa.text('false'))
    
    # ========== 4. subscription_points_history 表：添加缺失的字段 ==========
    columns = [col['name'] for col in inspector.get_columns('subscription_points_history')]
    
    # 4.1 添加 uuid 字段
    if 'uuid' not in columns:
        op.add_column('subscription_points_history',
                     sa.Column('uuid', postgresql.UUID(as_uuid=False),
                              nullable=False,
                              server_default=sa.text('gen_random_uuid()')))
        # 检查索引是否已存在
        try:
            op.create_index('ix_subscription_points_history_uuid', 'subscription_points_history', ['uuid'], unique=True)
        except Exception:
            pass  # 索引可能已存在
    
    # 4.2 添加 user_id 字段
    if 'user_id' not in columns:
        # 先添加为可空，然后从 subscription 获取数据，最后设置为 NOT NULL
        op.add_column('subscription_points_history',
                     sa.Column('user_id', sa.Integer(), nullable=True))
        # 从 subscriptions 表获取 user_id
        op.execute("""
            UPDATE subscription_points_history sph
            SET user_id = s.user_id
            FROM subscriptions s
            WHERE sph.subscription_id = s.subscription_id
        """)
        # 设置为 NOT NULL 并添加外键
        op.alter_column('subscription_points_history', 'user_id',
                       existing_type=sa.Integer(),
                       nullable=False)
        # 检查外键是否已存在
        try:
            op.create_foreign_key('fk_subscription_points_history_user_id',
                                'subscription_points_history', 'users',
                                ['user_id'], ['user_id'])
        except Exception:
            pass  # 外键可能已存在
        # 检查索引是否已存在
        try:
            op.create_index('ix_subscription_points_history_user_id', 'subscription_points_history', ['user_id'], unique=False)
        except Exception:
            pass  # 索引可能已存在
    
    # 4.3 添加 order_id 字段
    if 'order_id' not in columns:
        # 先添加为可空，然后从 subscription 获取数据，最后设置为 NOT NULL
        op.add_column('subscription_points_history',
                     sa.Column('order_id', sa.Integer(), nullable=True))
        # 从 subscriptions 表获取 order_id
        op.execute("""
            UPDATE subscription_points_history sph
            SET order_id = s.order_id
            FROM subscriptions s
            WHERE sph.subscription_id = s.subscription_id
        """)
        # 设置为 NOT NULL 并添加外键
        op.alter_column('subscription_points_history', 'order_id',
                       existing_type=sa.Integer(),
                       nullable=False)
        # 检查外键是否已存在
        try:
            op.create_foreign_key('fk_subscription_points_history_order_id',
                                'subscription_points_history', 'orders',
                                ['order_id'], ['order_id'])
        except Exception:
            pass  # 外键可能已存在
        # 检查索引是否已存在
        try:
            op.create_index('ix_subscription_points_history_order_id', 'subscription_points_history', ['order_id'], unique=False)
        except Exception:
            pass  # 索引可能已存在
    
    # 4.4 添加 points_record_id 字段
    if 'points_record_id' not in columns:
        op.add_column('subscription_points_history',
                     sa.Column('points_record_id', sa.Integer(), nullable=True))
        # 检查外键是否已存在
        try:
            op.create_foreign_key('fk_subscription_points_history_points_record_id',
                                'subscription_points_history', 'points_records',
                                ['points_record_id'], ['record_id'])
        except Exception:
            pass  # 外键可能已存在
        # 检查索引是否已存在
        try:
            op.create_index('ix_subscription_points_history_points_record_id', 'subscription_points_history', ['points_record_id'], unique=False)
        except Exception:
            pass  # 索引可能已存在
    
    # 4.5 添加 creem_invoice_id 字段
    if 'creem_invoice_id' not in columns:
        op.add_column('subscription_points_history',
                     sa.Column('creem_invoice_id', sa.String(length=100), nullable=True))
        # 检查索引是否已存在
        try:
            op.create_index('ix_subscription_points_history_creem_invoice_id', 'subscription_points_history', ['creem_invoice_id'], unique=False)
        except Exception:
            pass  # 索引可能已存在
    
    # 4.6 确保 created_at 字段存在
    if 'created_at' not in columns:
        op.add_column('subscription_points_history',
                     sa.Column('created_at', sa.DateTime(timezone=True),
                              nullable=True,
                              server_default=sa.text('now()')))
    
    # ========== 5. subscription_points_history 表：修复 payment_method 的可空性 ==========
    columns = [col['name'] for col in inspector.get_columns('subscription_points_history')]
    if 'payment_method' in columns:
        payment_col = next((col for col in inspector.get_columns('subscription_points_history') if col['name'] == 'payment_method'), None)
        if payment_col and not payment_col['nullable']:
            # 修改为可空
            op.alter_column('subscription_points_history', 'payment_method',
                          existing_type=sa.String(length=20),
                          nullable=True)


def downgrade() -> None:
    """回滚操作"""
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # 回滚 subscription_points_history 的修改
    columns = [col['name'] for col in inspector.get_columns('subscription_points_history')]
    
    # 恢复 payment_method 为 NOT NULL
    if 'payment_method' in columns:
        op.execute("UPDATE subscription_points_history SET payment_method = 'creem' WHERE payment_method IS NULL")
        op.alter_column('subscription_points_history', 'payment_method',
                       existing_type=sa.String(length=20),
                       nullable=False)
    
    # 删除添加的字段
    if 'creem_invoice_id' in columns:
        op.drop_index('ix_subscription_points_history_creem_invoice_id', table_name='subscription_points_history')
        op.drop_column('subscription_points_history', 'creem_invoice_id')
    
    if 'points_record_id' in columns:
        op.drop_index('ix_subscription_points_history_points_record_id', table_name='subscription_points_history')
        op.drop_constraint('fk_subscription_points_history_points_record_id', 'subscription_points_history', type_='foreignkey')
        op.drop_column('subscription_points_history', 'points_record_id')
    
    if 'order_id' in columns:
        op.drop_index('ix_subscription_points_history_order_id', table_name='subscription_points_history')
        op.drop_constraint('fk_subscription_points_history_order_id', 'subscription_points_history', type_='foreignkey')
        op.drop_column('subscription_points_history', 'order_id')
    
    if 'user_id' in columns:
        op.drop_index('ix_subscription_points_history_user_id', table_name='subscription_points_history')
        op.drop_constraint('fk_subscription_points_history_user_id', 'subscription_points_history', type_='foreignkey')
        op.drop_column('subscription_points_history', 'user_id')
    
    if 'uuid' in columns:
        op.drop_index('ix_subscription_points_history_uuid', table_name='subscription_points_history')
        op.drop_column('subscription_points_history', 'uuid')
    
    if 'created_at' in columns:
        op.drop_column('subscription_points_history', 'created_at')
    
    # 恢复 subscriptions 的修改
    columns = [col['name'] for col in inspector.get_columns('subscriptions')]
    if 'points_amount' not in columns:
        op.add_column('subscriptions',
                     sa.Column('points_amount', sa.Integer(), nullable=True))
        op.execute("UPDATE subscriptions SET points_amount = points_per_period WHERE points_amount IS NULL")
        op.alter_column('subscriptions', 'points_amount',
                       existing_type=sa.Integer(),
                       nullable=False)
    
    if 'cancel_at_period_end' in columns:
        op.alter_column('subscriptions', 'cancel_at_period_end',
                       existing_type=sa.Boolean(),
                       nullable=True,
                       server_default=None)
    
    # 恢复 products 的修改
    columns = [col['name'] for col in inspector.get_columns('products')]
    if 'synced_at' not in columns:
        op.add_column('products',
                     sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True))
