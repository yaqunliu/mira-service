"""Add temporary points table and permanent_points field

Revision ID: add_temp_points
Revises: f5g6h7i8j9k0
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'add_temp_points'
down_revision = 'f5g6h7i8j9k0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 为 points_accounts 表添加 permanent_points 字段
    op.add_column('points_accounts', 
        sa.Column('permanent_points', sa.Integer(), nullable=False, server_default='0')
    )
    
    # 2. 创建临时积分表
    op.create_table('temporary_points',
        sa.Column('temp_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('source_type', sa.String(length=20), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expire_record_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['points_accounts.account_id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
        sa.ForeignKeyConstraint(['expire_record_id'], ['points_records.record_id'], ),
        sa.PrimaryKeyConstraint('temp_id')
    )
    
    # 创建索引
    op.create_index(op.f('ix_temporary_points_temp_id'), 'temporary_points', ['temp_id'], unique=False)
    op.create_index(op.f('ix_temporary_points_account_id'), 'temporary_points', ['account_id'], unique=False)
    op.create_index(op.f('ix_temporary_points_user_id'), 'temporary_points', ['user_id'], unique=False)
    op.create_index(op.f('ix_temporary_points_source_type'), 'temporary_points', ['source_type'], unique=False)
    op.create_index(op.f('ix_temporary_points_expires_at'), 'temporary_points', ['expires_at'], unique=False)
    op.create_index(op.f('ix_temporary_points_expire_record_id'), 'temporary_points', ['expire_record_id'], unique=False)
    op.create_index(op.f('ix_temporary_points_created_at'), 'temporary_points', ['created_at'], unique=False)
    
    # 3. 迁移现有数据：将长期积分迁移到 permanent_points
    # 计算每个账户的长期积分 = total_points - 未过期的临时积分（从 points_records 查询）
    op.execute("""
        UPDATE points_accounts pa
        SET permanent_points = (
            SELECT COALESCE(pa2.total_points, 0) - COALESCE(SUM(pr.points), 0)
            FROM points_accounts pa2
            LEFT JOIN points_records pr ON pr.user_id = pa2.user_id
                AND pr.points_type = 'daily_checkin'
                AND pr.record_type IN ('reward', 'checkin')
                AND pr.expires_at > NOW()
                AND pr.points > 0
            WHERE pa2.account_id = pa.account_id
            GROUP BY pa2.account_id
        )
        WHERE permanent_points = 0
    """)
    
    # 4. 迁移现有签到积分到 temporary_points 表
    op.execute("""
        INSERT INTO temporary_points (account_id, user_id, points, source_type, source_id, expires_at, expire_record_id, created_at)
        SELECT 
            pr.account_id,
            pr.user_id,
            pr.points,
            pr.operation_type as source_type,
            pr.record_id as source_id,
            pr.expires_at,
            NULL as expire_record_id,
            pr.created_at
        FROM points_records pr
        WHERE pr.points_type = 'daily_checkin'
            AND pr.record_type IN ('reward', 'checkin')
            AND pr.expires_at > NOW()
            AND pr.points > 0
    """)


def downgrade() -> None:
    # 删除临时积分表
    op.drop_index(op.f('ix_temporary_points_created_at'), table_name='temporary_points')
    op.drop_index(op.f('ix_temporary_points_expires_at'), table_name='temporary_points')
    op.drop_index(op.f('ix_temporary_points_source_type'), table_name='temporary_points')
    op.drop_index(op.f('ix_temporary_points_user_id'), table_name='temporary_points')
    op.drop_index(op.f('ix_temporary_points_account_id'), table_name='temporary_points')
    op.drop_index(op.f('ix_temporary_points_temp_id'), table_name='temporary_points')
    op.drop_table('temporary_points')
    
    # 删除 permanent_points 字段
    op.drop_column('points_accounts', 'permanent_points')
