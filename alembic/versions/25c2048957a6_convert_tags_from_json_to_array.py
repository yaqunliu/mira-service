"""convert_tags_from_json_to_array

Revision ID: 25c2048957a6
Revises: 87258fab8d0b
Create Date: 2025-11-18 15:59:29.348201

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '25c2048957a6'
down_revision = '87258fab8d0b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 将 JSON 类型转换为 ARRAY(String)
    # 注意：如果 tags 已经是 TEXT[] 类型（由 87258fab8d0b 迁移完成），则跳过此迁移
    # 检查列类型，如果是数组类型则跳过
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT data_type, udt_name
        FROM information_schema.columns 
        WHERE table_name = 'characters' AND column_name = 'tags'
    """))
    row = result.fetchone()
    
    # 如果列不存在或已经是数组类型，跳过转换
    if not row or row[0] == 'ARRAY':
        # 已经是数组类型或列不存在，跳过转换
        pass
    else:
        # 需要转换：使用分步转换：先创建临时列，转换数据，然后替换
        op.execute("""
            -- 添加临时列
            ALTER TABLE characters ADD COLUMN tags_temp TEXT[];
            
            -- 转换数据：将 JSON 数组转换为 PostgreSQL 数组
            UPDATE characters 
            SET tags_temp = CASE 
                WHEN tags IS NULL THEN NULL
                WHEN tags::text = 'null' THEN NULL
                ELSE (
                    SELECT array_agg(value)
                    FROM jsonb_array_elements_text(tags::jsonb) AS value
                )
            END;
            
            -- 删除旧列
            ALTER TABLE characters DROP COLUMN tags;
            
            -- 重命名临时列为 tags
            ALTER TABLE characters RENAME COLUMN tags_temp TO tags;
        """)


def downgrade() -> None:
    # 将 ARRAY(String) 转换回 JSON
    # 检查列类型，如果已经是 JSON 类型则跳过
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT data_type
        FROM information_schema.columns 
        WHERE table_name = 'characters' AND column_name = 'tags'
    """))
    row = result.fetchone()
    
    # 如果列不存在或已经是 JSON 类型，跳过转换
    if not row or row[0] in ('json', 'jsonb'):
        # 已经是 JSON 类型或列不存在，跳过转换
        pass
    else:
        # 需要转换：将数组转换为 JSON
        op.execute("""
            ALTER TABLE characters 
            ALTER COLUMN tags TYPE JSON 
            USING CASE 
                WHEN tags IS NULL THEN NULL
                ELSE array_to_json(tags)::json
            END
        """)
