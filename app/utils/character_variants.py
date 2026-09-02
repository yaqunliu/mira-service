"""
角色变体标识工具（en-plan.md Phase 3.5）

角色名此前同时承担三个职责：显示名、变体区分键、跨模块匹配键，
格式为 `角色名-年龄段-临时状态`（如 `周宇-少年-校服`），由 LLM 直接拼在 name 里。

本模块把三个职责拆开：
- `name` 只负责显示（人名或身份称呼，英文）
- `(name, age_group, state)` 三元组负责区分变体
- 跨模块引用一律用 `character_id`，不再做任何字符串匹配

这里只负责「把 LLM 输出归一化成可落库的字典」，不碰数据库。
"""
import re
from typing import Any, Dict, List, Optional

from app.core.logger import logger

# 与 Character.AGE_GROUPS 保持一致
AGE_GROUPS = ("child", "teen", "youth", "middle_aged", "elder")
VOICE_CHANNELS = ("phone", "intercom", "memory", "distant", "offscreen")

TYPE_ON_SCREEN = "on_screen"
TYPE_VOICE = "voice"

# 旁白说话人的规范名。narration 里 character_id 为空且 role 命中此集合时按旁白处理
NARRATOR_NAME = "Narrator"
NARRATOR_ALIASES = frozenset({
    "narrator", "narration", "voiceover", "voice-over", "voice over",
    "旁白", "解说",
})

# 年龄段的常见别名（LLM 可能输出中文、连字符或空格变体）
_AGE_GROUP_ALIASES = {
    "child": "child", "kid": "child", "儿童": "child",
    "teen": "teen", "teenager": "teen", "adolescent": "teen", "少年": "teen",
    "youth": "youth", "young adult": "youth", "young_adult": "youth",
    "adult": "youth", "青年": "youth",
    "middle_aged": "middle_aged", "middle aged": "middle_aged",
    "middle-aged": "middle_aged", "middleaged": "middle_aged", "中年": "middle_aged",
    "elder": "elder", "elderly": "elder", "senior": "elder", "old": "elder", "老年": "elder",
}

# 声音传播方式的常见别名
_VOICE_CHANNEL_ALIASES = {
    "phone": "phone", "telephone": "phone", "电话": "phone",
    "intercom": "intercom", "radio": "intercom", "broadcast": "intercom", "对讲": "intercom",
    "memory": "memory", "flashback": "memory", "回忆": "memory",
    "distant": "distant", "far": "distant", "远处": "distant",
    "offscreen": "offscreen", "off-screen": "offscreen", "off screen": "offscreen",
    "voiceover": "offscreen", "画外音": "offscreen",
}

# 旧格式（中文键）到新格式的字段映射，仅用于兼容分支
_LEGACY_FIELD_MAP = {
    "基础信息": "basic_info",
    "容貌特征": "appearance",
    "身材特征": "body",
    "头发": "hair",
    "服装": "clothing",
    "特征标签": "tags",
    "音色描述": "voice_description",
}


def is_narrator(role: Optional[str]) -> bool:
    """判断一个说话人名是否表示旁白"""
    if not role:
        return False
    return role.strip().lower() in NARRATOR_ALIASES


def normalize_age_group(value: Any) -> Optional[str]:
    """归一化年龄段；无法识别时返回 None（而不是塞一个 '未知' 进库）"""
    if not value or not isinstance(value, str):
        return None
    key = value.strip().lower()
    if key in AGE_GROUPS:
        return key
    resolved = _AGE_GROUP_ALIASES.get(key)
    if not resolved:
        logger.warning(f"[character_variants] 无法识别的 age_group: {value!r}，置空")
    return resolved


def normalize_state(value: Any) -> Optional[str]:
    """
    归一化临时状态。日常状态统一存 None，避免 ''/'null'/'none' 与 None 混用
    导致同一个角色被当成两个变体重复建档。
    """
    if not value or not isinstance(value, str):
        return None
    state = " ".join(value.strip().lower().split())
    if not state or state in ("null", "none", "n/a", "-", "—", "无", "默认", "normal", "default"):
        return None
    return state[:120]


def normalize_character_type(value: Any) -> str:
    """归一化角色类型，缺省视为出镜角色"""
    if isinstance(value, str) and value.strip().lower() in (TYPE_VOICE, "voice_only", "voice-only"):
        return TYPE_VOICE
    return TYPE_ON_SCREEN


def normalize_voice_channel(value: Any) -> Optional[str]:
    """归一化声音传播方式"""
    if not value or not isinstance(value, str):
        return None
    key = value.strip().lower()
    if key in VOICE_CHANNELS:
        return key
    return _VOICE_CHANNEL_ALIASES.get(key)


def normalize_tags(value: Any) -> Optional[List[str]]:
    """特征标签归一化成字符串数组（兼容顿号/逗号分隔的字符串）"""
    if isinstance(value, list):
        tags = [str(t).strip() for t in value if str(t).strip()]
        return tags or None
    if isinstance(value, str):
        raw = value.replace("、", ",").replace("，", ",")
        tags = [t.strip() for t in raw.split(",") if t.strip()]
        return tags or None
    return None


def variant_key(name: str, age_group: Optional[str], state: Optional[str]) -> tuple:
    """角色变体的去重键。落库查重与本轮内去重都用它"""
    return ((name or "").strip(), age_group, state)


def normalize_character(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    把 LLM 输出的单个角色归一化成可直接落库的字典。

    name 为空时返回 None——没有名字的角色条目无法引用，直接丢弃比塞 "Unnamed" 更安全。
    """
    if not isinstance(raw, dict):
        return None

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        logger.warning(f"[character_variants] 角色缺少 name，已跳过: {raw}")
        return None

    char_type = normalize_character_type(raw.get("character_type"))
    normalized = {
        "name": name.strip()[:100],
        "character_type": char_type,
        "basic_info": (raw.get("basic_info") or "")[:500] or None,
        "voice_description": (raw.get("voice_description") or "")[:500] or None,
    }

    if char_type == TYPE_VOICE:
        # 声音角色不出镜：不落任何外貌字段，age_group / state 留空
        normalized.update({
            "age_group": None,
            "state": None,
            "voice_channel": normalize_voice_channel(raw.get("voice_channel")),
            "appearance": None,
            "body": None,
            "hair": None,
            "clothing": None,
            "tags": None,
        })
    else:
        normalized.update({
            "age_group": normalize_age_group(raw.get("age_group")),
            "state": normalize_state(raw.get("state")),
            "voice_channel": None,
            "appearance": raw.get("appearance") or None,
            "body": raw.get("body") or None,
            "hair": raw.get("hair") or None,
            "clothing": raw.get("clothing") or None,
            "tags": normalize_tags(raw.get("tags")),
        })

    return normalized


def parse_analysis_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    从角色分析的 LLM 返回里取出归一化后的角色列表，并按变体键去重。

    主路径是新格式 `{"characters": [...]}`。
    同时容忍旧格式 `{"人物特征库": {"出镜角色": {...}, "声音角色": {...}}}`——
    prompt 已改英文，但弱模型偶尔会退回旧习惯，这里兜住以免整条链路硬失败。
    """
    if not isinstance(result, dict):
        return []

    raw_characters = result.get("characters")
    if not isinstance(raw_characters, list):
        raw_characters = _parse_legacy_result(result)

    characters: List[Dict[str, Any]] = []
    seen = set()
    for raw in raw_characters:
        normalized = normalize_character(raw)
        if not normalized:
            continue
        key = variant_key(normalized["name"], normalized["age_group"], normalized["state"])
        if key in seen:
            logger.warning(f"[character_variants] LLM 输出了重复变体，已去重: {key}")
            continue
        seen.add(key)
        characters.append(normalized)

    return characters


def _parse_legacy_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    兼容分支：把旧的「按角色名做键」的中文格式摊平成数组。

    旧格式把年龄段与状态拼在角色名里（"陶未-青年-落魄"），这里**不做拆分**——
    猜测拆分点比保留原样更容易出错。整串留在 name 里，age_group / state 留空，
    行为退化成改造前的样子，并打 warning 以便在监控里看见。
    """
    library = result.get("人物特征库")
    if not isinstance(library, dict):
        return []

    on_screen = library.get("出镜角色")
    voice = library.get("声音角色")
    if not isinstance(on_screen, dict) and not isinstance(voice, dict):
        # 更旧的格式：人物特征库本身就是 {角色名: 特征}
        on_screen, voice = library, {}

    logger.warning(
        "[character_variants] LLM 返回了旧的中文角色格式，已按兼容分支解析。"
        "角色名将保持原样（含年龄段/状态后缀），age_group / state 为空"
    )

    flattened: List[Dict[str, Any]] = []
    for char_type, section in ((TYPE_ON_SCREEN, on_screen), (TYPE_VOICE, voice)):
        if not isinstance(section, dict):
            continue
        for name, info in section.items():
            if not isinstance(info, dict):
                continue
            entry = {"name": name, "character_type": char_type}
            for legacy_key, new_key in _LEGACY_FIELD_MAP.items():
                if legacy_key in info:
                    entry[new_key] = info[legacy_key]
            flattened.append(entry)

    return flattened


def build_historical_library(characters: List[Any]) -> List[Dict[str, Any]]:
    """
    把已存在的角色整理成传给 LLM 的历史角色库（数组格式）。

    带上 age_group / state 是为了让 LLM 能按三元组判断复用还是新建；
    带上已有的英文 name 是为了让跨章节的音译保持一致——
    这是重复建档最常见的诱因。
    """
    library = []
    for char in characters:
        entry = {
            "name": char.name,
            "character_type": char.character_type or TYPE_ON_SCREEN,
            "age_group": char.age_group,
            "state": char.state,
            "basic_info": char.basic_info or "",
            "voice_description": char.voice_description or "",
        }
        if (char.character_type or TYPE_ON_SCREEN) != TYPE_VOICE:
            entry.update({
                "appearance": char.appearance or "",
                "body": char.body or "",
                "hair": char.hair or "",
                "clothing": char.clothing or "",
                "tags": char.tags if char.tags else "",
            })
        else:
            entry["voice_channel"] = char.voice_channel
        library.append(entry)
    return library


def format_character_list_for_prompt(characters: List[Any]) -> str:
    """
    把角色列表渲染成注入分镜拆解 prompt 的表格。

    带上 id 是关键——分镜拆解要求 LLM 用 id 引用角色，而不是复述角色名。
    角色名一旦被复述，就必须在消费端做字符串匹配，那正是本轮要消灭的东西。
    """
    lines = []
    for char in characters:
        lines.append(
            "- id={id} | name={name} | type={ctype} | age_group={age} | state={state}{channel}".format(
                id=char.character_id,
                name=char.name,
                ctype=char.character_type or TYPE_ON_SCREEN,
                age=char.age_group or "-",
                state=char.state or "-",
                channel=f" | voice_channel={char.voice_channel}" if char.voice_channel else "",
            )
        )
    return "\n".join(lines)


def resolve_narration_items(
    raw_narration: Any,
    char_by_id: Dict[int, Any],
    shot_label: str = "",
) -> List[Dict[str, Any]]:
    """
    把 LLM 输出的台词列表归一化成落库用的 narration。

    LLM 侧输出 `[{"character_id": 42, "content": "..."}]`（旁白用 character_id: null）。
    落库形态额外带上展示名，以便前端无需回查角色表：

        [{"角色": "Zhou Yu", "内容": "...", "character_id": 42}]

    `角色` / `内容` 两个中文键在 Phase 4 统一改成 `role` / `content`；
    本轮只新增 `character_id`，保持前端不动。

    未知 character_id 会打 warning 并退化成旁白——静默丢台词比配错音色更糟。
    """
    if isinstance(raw_narration, str):
        text = raw_narration.strip()
        return [{"角色": NARRATOR_NAME, "内容": text, "character_id": None}] if text else []

    if not isinstance(raw_narration, list):
        return []

    items = []
    for entry in raw_narration:
        if isinstance(entry, str):
            text = entry.strip()
            if text:
                items.append({"角色": NARRATOR_NAME, "内容": text, "character_id": None})
            continue

        if not isinstance(entry, dict):
            continue

        content = entry.get("content") or entry.get("内容") or entry.get("text") or ""
        if not isinstance(content, str) or not content.strip():
            continue

        character_id = entry.get("character_id")
        role = entry.get("role") or entry.get("角色")

        if character_id is not None:
            char = char_by_id.get(character_id)
            if char:
                role = char.name
            else:
                logger.warning(
                    f"[character_variants] {shot_label} 台词引用了不存在的 character_id="
                    f"{character_id}，按旁白处理"
                )
                character_id = None
                role = role or NARRATOR_NAME

        if not role or is_narrator(role):
            role = NARRATOR_NAME
            character_id = None

        items.append({"角色": role, "内容": content.strip(), "character_id": character_id})

    return items


def strip_leaked_character_ids(
    description: Any,
    char_by_id: Dict[int, Any],
    shot_label: str = "",
) -> str:
    """
    把 description 里泄漏的裸 character_id 换回角色名。

    分镜拆解 prompt 反复要求「角色一律用 id 引用，禁止输出角色名」，但那条规则只针对
    on_screen_character_ids / voice_character_ids / narration[].character_id 三个字段。
    LLM 会把它过度泛化到 description 上，输出 "Medium close-up, centered: 10 carries
    a stack of textbooks..."——而 description 是直接显示在前端列表里的叙述文本。

    prompt 侧已加了错误示例 6 明确禁止；这里是兜底，避免裸数字直接进 UI。

    **只替换出现在小句开头的 id**（字符串开头，或紧跟 : ： , ， 。 . ! ! ? ? 之后）。
    这正是实际观察到的错误形态："近景居中: 10抱着一摞新课本..."。
    非小句开头的数字不动——正则分不清 "10 carries textbooks"（角色）和
    "waits 10 minutes"（时长）、"Shot 1-10"（编号），误改比不改更糟：
    把 "waits 10 minutes" 改成 "waits Tao Wei minutes" 会造出一个更难发现的新 bug。
    这类残留只打 warning，交给 prompt 侧和人工复核。
    """
    if not isinstance(description, str) or not description.strip():
        return description if isinstance(description, str) else ""

    if not char_by_id:
        return description

    # 长 id 优先，避免 id=1 抢先命中 id=10 的前缀
    ids_desc = sorted(char_by_id, key=lambda cid: len(str(cid)), reverse=True)

    # 小句开头：字符串起始，或标点（中英文冒号/逗号/句号/问号/叹号）后可带空白
    clause_start = r"(?:^|(?<=[:：,，。.!！?？]))\s*"

    replaced = []
    result = description
    for character_id in ids_desc:
        char = char_by_id.get(character_id)
        name = getattr(char, "name", None)
        if not name:
            continue
        pattern = rf"({clause_start}){character_id}(?![0-9A-Za-z])"
        result, count = re.subn(pattern, rf"\1{name}", result)
        if count:
            replaced.append(f"{character_id}->{name}")

    if replaced:
        logger.warning(
            f"[character_variants] {shot_label} description 小句开头泄漏了 character_id，"
            f"已替换为角色名: {', '.join(replaced)}"
        )

    # 残留的裸 id 只告警不改写（可能是时长/编号等正常数字，无法可靠区分）
    leftover = [
        cid for cid in char_by_id
        if re.search(rf"(?<![0-9A-Za-z-]){cid}(?![0-9A-Za-z-])", result)
    ]
    if leftover:
        logger.warning(
            f"[character_variants] {shot_label} description 中仍有疑似 character_id 的裸数字 "
            f"{leftover}（未改写，可能是正常数字）: {result[:120]}"
        )

    return result


def resolve_character_ids(
    raw_ids: Any,
    char_by_id: Dict[int, Any],
    shot_label: str = "",
) -> List[Any]:
    """
    把 LLM 输出的 character_id 数组解析成 Character 对象列表。

    **不做任何名字匹配**——改造前这里是 `if name in db_char_name or db_char_name in name`
    的子串模糊匹配，中文名下勉强能跑，英文名下 "Lin" 会同时命中 "Lin Xia" 和 "Linda"。
    未知 ID 一律打 warning，不静默跳过。
    """
    if not isinstance(raw_ids, list):
        return []

    resolved = []
    for raw_id in raw_ids:
        try:
            character_id = int(raw_id)
        except (TypeError, ValueError):
            logger.warning(f"[character_variants] {shot_label} 角色引用不是合法 ID: {raw_id!r}")
            continue

        char = char_by_id.get(character_id)
        if char is None:
            logger.warning(
                f"[character_variants] {shot_label} 引用了不存在的 character_id={character_id} "
                f"(可用: {sorted(char_by_id)})"
            )
            continue
        resolved.append(char)

    return resolved
