"""add assets table

Revision ID: 20260104_assets
Revises: a75f35aab7d1
Create Date: 2026-01-04 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '20260104_assets'
down_revision = 'a75f35aab7d1'
branch_labels = None
depends_on = None


def upgrade():
    # 创建素材表
    op.create_table(
        'assets',
        sa.Column('asset_id', sa.Integer(), autoincrement=True, nullable=False, comment='素材ID'),
        sa.Column('uuid', sa.String(length=36), nullable=False, comment='UUID'),
        sa.Column('novel_id', sa.Integer(), nullable=False, comment='关联的小说ID'),
        sa.Column('type', sa.Enum('audio', 'image', 'video', name='assettype'), nullable=False, comment='素材类型'),
        sa.Column('name', sa.String(length=255), nullable=False, comment='素材名称'),
        sa.Column('url', sa.String(length=512), nullable=False, comment='US3存储地址'),
        sa.Column('size', sa.BigInteger(), nullable=True, comment='文件大小(字节)'),
        sa.Column('duration', sa.Integer(), nullable=True, comment='时长(秒),仅音频/视频'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=True, comment='更新时间'),
        sa.PrimaryKeyConstraint('asset_id')
    )

    # 创建索引
    op.create_index('ix_assets_asset_id', 'assets', ['asset_id'], unique=False)
    op.create_index('ix_assets_uuid', 'assets', ['uuid'], unique=True)
    op.create_index('ix_assets_novel_id', 'assets', ['novel_id'], unique=False)


def downgrade():
    # 删除索引
    op.drop_index('ix_assets_novel_id', table_name='assets')
    op.drop_index('ix_assets_uuid', table_name='assets')
    op.drop_index('ix_assets_asset_id', table_name='assets')

    # 删除表
    op.drop_table('assets')
