"""add scene_ids and novel_id to scenes

Revision ID: 1767578870_scene
Revises: rename_product_id_fields_001
Create Date: 2026-01-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1767578870_scene'
down_revision = ('rename_product_id_fields_001', '20260104_assets')
branch_labels = None
depends_on = None


def upgrade():
    # 添加 scene_ids 到 creations 表
    op.add_column('creations', sa.Column('scene_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # 添加 novel_id 到 scenes 表
    op.add_column('scenes', sa.Column('novel_id', sa.Integer(), nullable=True))
    op.add_column('scenes', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))

    # 创建索引
    op.create_index(op.f('ix_scenes_novel_id'), 'scenes', ['novel_id'], unique=False)
    op.create_index(op.f('ix_scenes_deleted_at'), 'scenes', ['deleted_at'], unique=False)

    # 创建外键约束
    op.create_foreign_key('fk_scenes_novel_id', 'scenes', 'novels', ['novel_id'], ['novel_id'])


def downgrade():
    # 删除外键约束
    op.drop_constraint('fk_scenes_novel_id', 'scenes', type_='foreignkey')

    # 删除索引
    op.drop_index(op.f('ix_scenes_deleted_at'), table_name='scenes')
    op.drop_index(op.f('ix_scenes_novel_id'), table_name='scenes')

    # 删除列
    op.drop_column('scenes', 'deleted_at')
    op.drop_column('scenes', 'novel_id')
    op.drop_column('creations', 'scene_ids')
