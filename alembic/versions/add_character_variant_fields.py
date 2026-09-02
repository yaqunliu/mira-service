"""Add structured variant fields to characters (age_group / state / character_type / voice_channel)

角色标识体系重构（en-plan.md Phase 3.5.1）：

角色名此前同时承担三个职责——显示名、变体区分键、跨模块匹配键，
格式为 `角色名-年龄段-临时状态`（如 `周宇-少年-校服`），全部由 LLM 拼在 name 里。
本迁移把变体信息从 name 中拆出来变成结构化字段，name 从此只存人名或身份称呼。

同时把声音角色的判定从 `basic_info == '声音角色'` 这个字符串哨兵
搬迁到独立的 character_type 列。

注意：存量角色的 name 保持原样（不翻译、不拆分），age_group / state 留空。
新逻辑只对新建 creation 生效。

Revision ID: add_character_variant_fields
Revises: add_event_type_values
Create Date: 2026-09-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_character_variant_fields'
down_revision = 'add_event_type_values'
branch_labels = None
depends_on = None

# 旧数据用 basic_info 存这个哨兵值来标记声音角色
LEGACY_VOICE_SENTINEL = '声音角色'


def upgrade() -> None:
    op.add_column('characters', sa.Column('age_group', sa.String(length=20), nullable=True))
    op.add_column('characters', sa.Column('state', sa.String(length=120), nullable=True))
    op.add_column(
        'characters',
        sa.Column('character_type', sa.String(length=20), nullable=False, server_default='on_screen'),
    )
    op.add_column('characters', sa.Column('voice_channel', sa.String(length=20), nullable=True))

    # 列语义搬迁：把 basic_info 哨兵表达的"声音角色"落到 character_type。
    # 这不是文案翻译（存量角色名依决策不迁移），而是必须做的收口——
    # 否则老数据的声音角色会被当成出镜角色送去生图，白烧积分。
    op.execute(
        sa.text(
            "UPDATE characters SET character_type = 'voice' WHERE basic_info = :sentinel"
        ).bindparams(sentinel=LEGACY_VOICE_SENTINEL)
    )

    # 变体查询走 (creation_id, name, age_group, state)，加索引避免落库阶段全表扫
    op.create_index(
        'ix_characters_variant_lookup',
        'characters',
        ['creation_id', 'name', 'age_group', 'state'],
    )


def downgrade() -> None:
    op.drop_index('ix_characters_variant_lookup', table_name='characters')

    # 把 character_type 反写回 basic_info 哨兵，保证 downgrade 后旧代码仍能识别声音角色
    op.execute(
        sa.text(
            "UPDATE characters SET basic_info = :sentinel "
            "WHERE character_type = 'voice' AND (basic_info IS NULL OR basic_info = '')"
        ).bindparams(sentinel=LEGACY_VOICE_SENTINEL)
    )

    op.drop_column('characters', 'voice_channel')
    op.drop_column('characters', 'character_type')
    op.drop_column('characters', 'state')
    op.drop_column('characters', 'age_group')
