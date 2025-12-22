"""Add extra_data to creations

Revision ID: h1i2j3k4l5m6
Revises: merge_uuid_supabase_temp
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

Note: 模型配置使用 Python 代码中的工厂模式管理（app/core/model_config.py），
不再存储在数据库表中。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'h1i2j3k4l5m6'
down_revision = 'merge_uuid_supabase_temp'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 为 creations 表添加 extra_data 字段
    # 注意：模型配置现在使用 Python 代码中的工厂模式管理，不再存储在数据库中
    # 检查列是否已存在（避免重复添加）
    conn = op.get_bind()
    inspector = inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('creations')]
    
    if 'extra_data' not in columns:
        op.add_column('creations', 
            sa.Column('extra_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
        )


def downgrade() -> None:
    # 删除 extra_data 字段
    op.drop_column('creations', 'extra_data')

