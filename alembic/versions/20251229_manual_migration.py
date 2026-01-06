"""Manual migration record

Revision ID: 20251229_manual_migration
Revises: 4d440ea3d415
Create Date: 2025-12-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20251229_manual_migration'
down_revision = '4d440ea3d415'
branch_labels = None
depends_on = None

def upgrade() -> None:
    """手动迁移：添加场景模型中的JSONB字段支持"""
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # 检查并确保场景表中的JSONB字段存在
    columns = [col['name'] for col in inspector.get_columns('scenes')]
    
    # 检查 environment_setting 字段
    if 'environment_setting' not in columns:
        op.add_column('scenes',
                     sa.Column('environment_setting', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    
    # 检查 environment_images 字段
    if 'environment_images' not in columns:
        op.add_column('scenes',
                     sa.Column('environment_images', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    
    # 检查 lighting_info 字段
    if 'lighting_info' not in columns:
        op.add_column('scenes',
                     sa.Column('lighting_info', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    
    # 检查 environment_details 字段
    if 'environment_details' not in columns:
        op.add_column('scenes',
                     sa.Column('environment_details', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    
    # 检查 status_detail 字段
    if 'status_detail' not in columns:
        op.add_column('scenes',
                     sa.Column('status_detail', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

def downgrade() -> None:
    """回滚操作"""
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # 检查并删除场景表中的JSONB字段
    columns = [col['name'] for col in inspector.get_columns('scenes')]
    
    if 'environment_setting' in columns:
        op.drop_column('scenes', 'environment_setting')
    
    if 'environment_images' in columns:
        op.drop_column('scenes', 'environment_images')
    
    if 'lighting_info' in columns:
        op.drop_column('scenes', 'lighting_info')
    
    if 'environment_details' in columns:
        op.drop_column('scenes', 'environment_details')
    
    if 'status_detail' in columns:
        op.drop_column('scenes', 'status_detail')
