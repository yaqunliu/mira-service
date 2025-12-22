"""Rename product_id fields to origin_product_id

Revision ID: rename_product_id_fields_001
Revises: add_subscription_fields_001
Create Date: 2025-01-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'rename_product_id_fields_001'
down_revision = 'add_subscription_fields_001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 检查列是否已存在
    conn = op.get_bind()
    inspector = inspect(conn)
    
    try:
        columns = [col['name'] for col in inspector.get_columns('products')]
    except Exception:
        # 如果表不存在，跳过
        return
    
    # 如果 origin_product_id 已存在，且旧字段已删除，跳过
    if 'origin_product_id' in columns and 'creem_product_id' not in columns and 'wechat_product_id' not in columns:
        return
    
    # 添加 origin_product_id 字段（如果不存在）
    if 'origin_product_id' not in columns:
        try:
            op.add_column('products', sa.Column('origin_product_id', sa.String(length=100), nullable=True))
        except Exception:
            pass  # 如果添加失败，可能已存在
        
        # 迁移数据：优先使用 creem_product_id，如果没有则使用 wechat_product_id
        if 'creem_product_id' in columns:
            try:
                conn.execute(sa.text("""
                    UPDATE products 
                    SET origin_product_id = creem_product_id 
                    WHERE origin_product_id IS NULL AND creem_product_id IS NOT NULL
                """))
                conn.commit()
            except Exception:
                conn.rollback()
        
        if 'wechat_product_id' in columns:
            try:
                conn.execute(sa.text("""
                    UPDATE products 
                    SET origin_product_id = wechat_product_id 
                    WHERE origin_product_id IS NULL AND wechat_product_id IS NOT NULL
                """))
                conn.commit()
            except Exception:
                conn.rollback()
        
        # 创建索引
        try:
            indexes = [idx['name'] for idx in inspector.get_indexes('products')]
            if 'ix_products_origin_product_id' not in indexes:
                op.create_index(op.f('ix_products_origin_product_id'), 'products', ['origin_product_id'], unique=False)
        except Exception:
            pass
    
    # 删除旧字段和索引（使用独立的SQL语句，避免事务问题）
    try:
        indexes = [idx['name'] for idx in inspector.get_indexes('products')]
    except Exception:
        indexes = []
    
    # 删除 creem_product_id 相关
    if 'creem_product_id' in columns:
        # 先删除索引
        if 'ix_products_creem_product_id' in indexes:
            try:
                conn.execute(sa.text("DROP INDEX IF EXISTS ix_products_creem_product_id"))
                conn.commit()
            except Exception:
                conn.rollback()
        # 再删除列
        try:
            conn.execute(sa.text("ALTER TABLE products DROP COLUMN IF EXISTS creem_product_id"))
            conn.commit()
        except Exception:
            conn.rollback()
    
    # 删除 wechat_product_id 相关
    if 'wechat_product_id' in columns:
        # 先删除索引
        if 'ix_products_wechat_product_id' in indexes:
            try:
                conn.execute(sa.text("DROP INDEX IF EXISTS ix_products_wechat_product_id"))
                conn.commit()
            except Exception:
                conn.rollback()
        # 再删除列
        try:
            conn.execute(sa.text("ALTER TABLE products DROP COLUMN IF EXISTS wechat_product_id"))
            conn.commit()
        except Exception:
            conn.rollback()


def downgrade() -> None:
    # 恢复旧字段
    conn = op.get_bind()
    inspector = inspect(conn)
    
    try:
        columns = [col['name'] for col in inspector.get_columns('products')]
    except Exception:
        return
    
    if 'origin_product_id' not in columns:
        return
    
    # 添加旧字段
    if 'creem_product_id' not in columns:
        try:
            op.add_column('products', sa.Column('creem_product_id', sa.String(length=100), nullable=True))
        except Exception:
            pass
    
    if 'wechat_product_id' not in columns:
        try:
            op.add_column('products', sa.Column('wechat_product_id', sa.String(length=100), nullable=True))
        except Exception:
            pass
    
    # 迁移数据回旧字段
    try:
        conn.execute(sa.text("""
            UPDATE products 
            SET creem_product_id = origin_product_id 
            WHERE payment_method = 'creem' AND origin_product_id IS NOT NULL
        """))
        conn.commit()
    except Exception:
        conn.rollback()
    
    try:
        conn.execute(sa.text("""
            UPDATE products 
            SET wechat_product_id = origin_product_id 
            WHERE payment_method = 'wechat' AND origin_product_id IS NOT NULL
        """))
        conn.commit()
    except Exception:
        conn.rollback()
    
    # 创建旧索引
    try:
        indexes = [idx['name'] for idx in inspector.get_indexes('products')]
        if 'ix_products_creem_product_id' not in indexes:
            op.create_index(op.f('ix_products_creem_product_id'), 'products', ['creem_product_id'], unique=False)
        if 'ix_products_wechat_product_id' not in indexes:
            op.create_index(op.f('ix_products_wechat_product_id'), 'products', ['wechat_product_id'], unique=False)
    except Exception:
        pass
    
    # 删除新字段
    try:
        op.drop_index(op.f('ix_products_origin_product_id'), table_name='products')
        op.drop_column('products', 'origin_product_id')
    except Exception:
        pass
