"""Add uuid to all tables

Revision ID: 8f1780b73480
Revises: f5g6h7i8j9k0
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = '8f1780b73480'
down_revision = 'f5g6h7i8j9k0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 为所有表添加uuid字段
    tables = [
        'users',
        'novels',
        'chapters',
        'creations',
        'characters',
        'scenes',
        'shots',
        'points_accounts',
        'points_records',
        'temporary_points'
    ]
    
    for table_name in tables:
        # 添加uuid列（先允许NULL，以便为现有记录生成值）
        op.add_column(
            table_name,
            sa.Column('uuid', postgresql.UUID(as_uuid=False), nullable=True)
        )
        
        # 为现有记录生成uuid
        # 注意：PostgreSQL的UUID类型列应该直接使用gen_random_uuid()，不需要::text转换
        op.execute(
            sa.text(f"""
                UPDATE {table_name} 
                SET uuid = gen_random_uuid() 
                WHERE uuid IS NULL
            """)
        )
        
        # 设置uuid为NOT NULL，并添加数据库层面的默认值
        # 注意：server_default不需要::text，因为列类型是UUID
        op.alter_column(
            table_name, 
            'uuid', 
            nullable=False,
            server_default=sa.text('gen_random_uuid()')
        )
        
        # 创建唯一索引
        op.create_index(
            f'ix_{table_name}_uuid',
            table_name,
            ['uuid'],
            unique=True
        )


def downgrade() -> None:
    # 删除所有表的uuid字段和索引
    tables = [
        'users',
        'novels',
        'chapters',
        'creations',
        'characters',
        'scenes',
        'shots',
        'points_accounts',
        'points_records',
        'temporary_points'
    ]
    
    for table_name in tables:
        op.drop_index(f'ix_{table_name}_uuid', table_name=table_name)
        op.drop_column(table_name, 'uuid')
