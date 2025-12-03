"""Add points system

Revision ID: f5g6h7i8j9k0
Revises: e4f5g6h7i8j9
Create Date: 2025-01-XX XX:XX:XX.XXXXXX

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f5g6h7i8j9k0'
down_revision = 'e4f5g6h7i8j9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建积分账户表
    op.create_table('points_accounts',
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('total_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('available_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('frozen_points', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
        sa.PrimaryKeyConstraint('account_id'),
        sa.UniqueConstraint('user_id')
    )
    op.create_index(op.f('ix_points_accounts_account_id'), 'points_accounts', ['account_id'], unique=False)
    op.create_index(op.f('ix_points_accounts_user_id'), 'points_accounts', ['user_id'], unique=True)
    
    # 创建积分记录表
    op.create_table('points_records',
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('record_type', sa.String(length=20), nullable=False),
        sa.Column('operation_type', sa.String(length=50), nullable=True),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('points_type', sa.String(length=20), nullable=True, server_default='normal'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('balance_before', sa.Integer(), nullable=False),
        sa.Column('balance_after', sa.Integer(), nullable=False),
        sa.Column('creation_id', sa.Integer(), nullable=True),
        sa.Column('novel_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('extra_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['points_accounts.account_id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ),
        sa.ForeignKeyConstraint(['creation_id'], ['creations.creation_id'], ),
        sa.ForeignKeyConstraint(['novel_id'], ['novels.novel_id'], ),
        sa.PrimaryKeyConstraint('record_id')
    )
    op.create_index(op.f('ix_points_records_record_id'), 'points_records', ['record_id'], unique=False)
    op.create_index(op.f('ix_points_records_account_id'), 'points_records', ['account_id'], unique=False)
    op.create_index(op.f('ix_points_records_user_id'), 'points_records', ['user_id'], unique=False)
    op.create_index(op.f('ix_points_records_record_type'), 'points_records', ['record_type'], unique=False)
    op.create_index(op.f('ix_points_records_operation_type'), 'points_records', ['operation_type'], unique=False)
    op.create_index(op.f('ix_points_records_creation_id'), 'points_records', ['creation_id'], unique=False)
    op.create_index(op.f('ix_points_records_novel_id'), 'points_records', ['novel_id'], unique=False)
    op.create_index(op.f('ix_points_records_created_at'), 'points_records', ['created_at'], unique=False)
    op.create_index(op.f('ix_points_records_expires_at'), 'points_records', ['expires_at'], unique=False)


def downgrade() -> None:
    # 删除积分记录表
    op.drop_index(op.f('ix_points_records_expires_at'), table_name='points_records')
    op.drop_index(op.f('ix_points_records_created_at'), table_name='points_records')
    op.drop_index(op.f('ix_points_records_novel_id'), table_name='points_records')
    op.drop_index(op.f('ix_points_records_creation_id'), table_name='points_records')
    op.drop_index(op.f('ix_points_records_operation_type'), table_name='points_records')
    op.drop_index(op.f('ix_points_records_record_type'), table_name='points_records')
    op.drop_index(op.f('ix_points_records_user_id'), table_name='points_records')
    op.drop_index(op.f('ix_points_records_account_id'), table_name='points_records')
    op.drop_index(op.f('ix_points_records_record_id'), table_name='points_records')
    op.drop_table('points_records')
    
    # 删除积分账户表
    op.drop_index(op.f('ix_points_accounts_user_id'), table_name='points_accounts')
    op.drop_index(op.f('ix_points_accounts_account_id'), table_name='points_accounts')
    op.drop_table('points_accounts')
