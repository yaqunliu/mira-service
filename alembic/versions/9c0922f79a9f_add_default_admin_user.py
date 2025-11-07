"""Add default admin user

Revision ID: 9c0922f79a9f
Revises: b1a0f05d6d52
Create Date: 2025-11-06 17:31:57.687928

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c0922f79a9f'
down_revision = 'b1a0f05d6d52'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 创建默认用户 (用户名: admin, 密码: admin123)
    # 使用预生成的 bcrypt 哈希值，避免在迁移时调用密码哈希函数
    # 密码: admin123
    default_password_hash = "$2b$12$rvPXWK2BIaRTyjww9q/YYudH5RnYpMj.robIE9vEZZBAZyqeDrYuy"
    op.execute(
        sa.text("""
            INSERT INTO users (username, email, hashed_password)
            SELECT 'admin', 'admin@example.com', :password_hash
            WHERE NOT EXISTS (SELECT 1 FROM users WHERE username = 'admin')
        """).bindparams(password_hash=default_password_hash)
    )


def downgrade() -> None:
    # 删除默认用户
    op.execute(sa.text("DELETE FROM users WHERE username = 'admin'"))
