"""Add AgentSession fields (creation_uuid, user_id, status)

Revision ID: 002
Revises: 47a3c98a9ad3
Create Date: 2026-01-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '47a3c98a9ad3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 检查字段是否已存在
    from sqlalchemy import text
    conn = op.get_bind()
    
    # 检查 creation_uuid
    result = conn.execute(text("""
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='agent_sessions' AND column_name='creation_uuid'
    """))
    if result.scalar() is None:
        op.add_column('agent_sessions', 
            sa.Column('creation_uuid', postgresql.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()'))
        )
        op.create_index('idx_agent_sessions_creation_uuid', 'agent_sessions', ['creation_uuid'])
    else:
        op.execute("DROP INDEX IF EXISTS idx_agent_sessions_creation_uuid")
        op.create_index('idx_agent_sessions_creation_uuid', 'agent_sessions', ['creation_uuid'])
    
    # 检查 user_id
    result = conn.execute(text("""
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='agent_sessions' AND column_name='user_id'
    """))
    if result.scalar() is None:
        op.add_column('agent_sessions',
            sa.Column('user_id', sa.Integer(), nullable=False, server_default='1')
        )
        op.create_index('idx_agent_sessions_user_id', 'agent_sessions', ['user_id'])
    else:
        op.execute("DROP INDEX IF EXISTS idx_agent_sessions_user_id")
        op.create_index('idx_agent_sessions_user_id', 'agent_sessions', ['user_id'])
    
    # 检查 status
    result = conn.execute(text("""
        SELECT 1 FROM information_schema.columns 
        WHERE table_name='agent_sessions' AND column_name='status'
    """))
    if result.scalar() is None:
        op.add_column('agent_sessions',
            sa.Column('status', sa.String(20), nullable=False, server_default='active')
        )
        op.create_index('idx_agent_sessions_status', 'agent_sessions', ['status'])
    else:
        op.execute("DROP INDEX IF EXISTS idx_agent_sessions_status")
        op.create_index('idx_agent_sessions_status', 'agent_sessions', ['status'])
    
    # 更新现有的记录
    op.execute("""
        UPDATE agent_sessions
        SET creation_uuid = (
            SELECT c.uuid
            FROM creations c
            WHERE c.creation_id = agent_sessions.creation_id
        )
        WHERE agent_sessions.creation_uuid IS NULL 
           OR agent_sessions.creation_uuid = '00000000-0000-0000-0000-000000000000'::uuid
    """)
    
    op.execute("""
        UPDATE agent_sessions
        SET user_id = c.owner_id
        FROM creations c
        WHERE c.creation_id = agent_sessions.creation_id
          AND agent_sessions.user_id = 1
    """)


def downgrade() -> None:
    op.drop_index('idx_agent_sessions_status', table_name='agent_sessions')
    op.drop_column('agent_sessions', 'status')
    
    op.drop_index('idx_agent_sessions_user_id', table_name='agent_sessions')
    op.drop_column('agent_sessions', 'user_id')
    
    op.drop_index('idx_agent_sessions_creation_uuid', table_name='agent_sessions')
    op.drop_column('agent_sessions', 'creation_uuid')
