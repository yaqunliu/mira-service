# mira-service 英文可交付改造计划

## Context

`mira-fe` 已完成英文化：URL 去掉语言前缀、`src/` 无残留硬编码中文、en/zh 各 2047 个 key 且集合一致。

但那只是**英文外壳**。用户跑一遍创作主流程，界面全英文，**生成出来的内容是中文**——剧本、角色、场景、分镜、旁白全是。落差比界面上残留几个中文严重得多。

本次目标：让后端产出的**内容**、**报错**、**数据契约**全部英文化，使「英文可交付」名副其实。

### 现状实测

| 项 | 现状 |
|---|---|
| prompt 文件 | `app/prompt/` 37 份 + `app/agent/` 9 份，合计 **8602 行** |
| 显式要求中文输出的 prompt | **7 处**（`agent_video_prompt_gen.md:125` 明写「必须使用中文」） |
| i18n 基础设施 | **完全没有**（`Accept-Language` / gettext / babel 全仓 0 命中） |
| 中文报错 `detail=` | **37 个文件** |
| 数据契约中文键 | `角色`/`内容` 44 处、`出镜角色`/`声音角色` 10 处、`旁白` 49 处，共 **15 个文件** |
| 含中文字面量的 py 文件 | 200 个（含注释，实际需改的远少于此） |
| voices 端点 | `language: str = Query(default="zh")`（`app/api/api_v1/endpoints/voices.py:24`） |
| 角色名 | LLM 按 `character_analysis.md` 生成 `角色名-年龄段-临时状态`（如 `周宇-少年-校服`），代码原样存库、原样渲染 |
| 把角色名当匹配键的代码 | **6 处**，其中 2 处失败时**静默降级**不报错（见 Phase 3.5） |
| 中文关键词表 | `character_state_identifier.py` 状态词表、`audio_tools._analyze_emotion` 情感词表——英文输入下命中率 0 |

### 已确认的决策

1. **image_prompt / video_prompt 也改英文**——用户在 `shot-detail-dialog` 里能看到并编辑它们，体验要统一。
   ⚠️ **这是本计划最大的技术风险**，见 Phase 3。
2. **数据契约本轮就改**，带 Alembic 数据迁移，前后端同步发版。
3. **TTS 英文音色库情况未知**，计划第一步先验证。
4. **中文人名一律音译**（汉语拼音，如 `周宇` → `Zhou Yu`），非人名的身份称呼意译（`班主任` → `Homeroom Teacher`）。
5. **角色名只存人名**，年龄段与临时状态改为 Character 表的结构化字段，不再拼进 `name`。
   跨引用改用 `character_id`，从根上消灭字符串匹配。见 Phase 3.5。
6. **存量角色名不迁移**——老 creation 的中文角色名保持原样，新逻辑只对新建 creation 生效。
   （注意：Phase 3.5 的**列语义搬迁**仍需一条 backfill SQL，那是 schema 收口不是文案翻译，不违反本决策。）

### 关键杠杆点（复用现有代码，不另起炉灶）

| 位置 | 作用 |
|---|---|
| `app/utils/file_utils.py:72` `read_prompt_file()` | **prompt 加载唯一主入口**，语言路由改这里 |
| `app/utils/ai_client.py:2999` | 第二条 prompt 加载路径，需一并收口 |
| `app/agent/prompts/loader.py:15` `load_prompt()` | agent prompt 加载器（带 YAML 头 + Jinja2） |
| `app/core/exceptions.py` | 13 个异常类的干净继承体系，**错误码就加在这里** |
| `app/middleware/error_handler.py` | 3 个全局处理器，响应格式统一收口点 |
| `alembic/versions/` | 53 个已有迁移，数据迁移基础设施现成 |
| `app/tasks/creation_task.py:141-261` | **角色落库唯一入口**，角色名在这里从 LLM 输出的 JSON 键变成 `Character.name` |
| `app/utils/ai_client.py:836` | `{{CHARACTER_LIST}}` 注入点，改成 ID 引用就改这一处 |

---

## Phase 0 — 前置验证与闸门（必须先做）

### 0.1 验证 Fish Audio 英文音色库

旁白英文化后 TTS 必须有英文音色，否则整条链路断在最后一步。**这是阻塞项**。

```bash
curl -s "$API/api/v1/voices?language=en&page_size=1" | jq .total
curl -s "$API/api/v1/voices?language=zh&page_size=1" | jq .total
```

- `en` 有数据 → 继续，`voices.py:24` 默认值改 `en`
- `en` 为 0 → **暂停 Phase 3 的旁白部分**，先解决音色源（Fish Audio 是否需要单独开通英文库 / 换 TTS 供应商）

注：`VoiceItem.languages` 是数组字段，需确认后端 `language` 查询参数究竟按什么过滤，以及音色数据导入时有没有打 `en` 标签。

> 前端已就绪：`mira-fe` 的 `voiceApi.getVoicesForDelivery()` 已改为「请求 `en` 音色、无数据时回退默认库」，
> 并在回退时打 `console.warn`。后端英文库确认可用后，那段回退逻辑可以拆掉。

### 0.2 建中文残留闸门

新增 `scripts/check_zh.py`，扫描 `app/` 下**字符串字面量与 f-string**中的中文（跳过注释、docstring、日志）。仿 `mira-fe/scripts/check-i18n.mjs` 的分级设计：

- 支持 `# zh-ignore` 行内豁免与文件头 `zh-ignore-file`
- 支持 `--baseline` / `--ratchet`，每批只降不升
- 加入 `pyproject.toml` 的 lint 流程

**没有闸门就没法证明「改干净了」，必须先做。**

### 0.3 建生成质量基线（Phase 3 的安全网）

因为要动喂给豆包的 prompt，必须能回答「改完之后画质有没有变差」。

固定 3 篇测试小说，用**当前中文 prompt** 跑完整流程，归档：
- 生成的角色图、场景图、分镜图（人工评分：一致性 / 画质 / 贴合度）
- 生成的视频片段
- 每步耗时与 token 消耗

存到 `tests/fixtures/generation_baseline/`。Phase 3 改完后用**同样 3 篇**重跑对比。

---

## Phase 1 — i18n 基础设施

后端目前 0 i18n。先把地基铺好，后面几个 Phase 才有地方落。

### 1.1 语言上下文

新增 `app/core/i18n.py`：

- `SUPPORTED_LOCALES = ("en", "zh")`，`DEFAULT_LOCALE = "en"`
- FastAPI 中间件解析 `Accept-Language`，写入 `contextvars.ContextVar`
- Celery 任务无 HTTP 上下文 → **任务入参显式带 `locale`**，由调用方传入；缺省 `en`

> 注意：`app/tasks/` 下的任务是异步执行的，contextvar 不跨进程。所有 `.delay()` / `.apply_async()` 调用点都要加 `locale` 参数。

### 1.2 错误码体系

改造 `app/core/exceptions.py`（13 个异常类）：

```python
class BaseServiceException(Exception):
    code: str = "internal_error"          # 新增：稳定错误码
    def __init__(self, message=None, status_code=500, detail=None, code=None, **params):
        self.code = code or self.code
        self.params = params              # 用于插值，如 character_id
        ...
```

`app/middleware/error_handler.py` 的响应体加 `code` 字段：

```json
{ "error": true, "code": "character_not_found", "message": "Character not found", "status_code": 404 }
```

**前端已经能吃这个**——`mira-fe/src/lib/api/client.ts` 的 `resolveErrorMessage()` 已按 HTTP status 映射英文文案，加了 `code` 之后可以升级成按业务码精确映射。

> 另注：前端目前只读 `data.message`，**不读 `data.detail`**。所以中文 `detail` 现在不会直接泄漏到界面，
> 但一旦前端改为读 `detail`，必须同步过一遍前端的 CJK 拦截函数。

### 1.3 文案资源

`app/i18n/messages/{en,zh}.json`，key 与错误码同名。提供 `t(key, locale, **params)`。
两份 key 集合一致由 Phase 0 的闸门校验。

---

## Phase 2 — 报错与状态值英文化

依赖 Phase 1。

### 2.1 报错 detail（37 个文件）

统一改成「错误码 + 英文 detail」：

```python
# 改前
raise NotFoundError(detail=f"角色不存在: character_id={character_id}")
# 改后
raise NotFoundError(code="character_not_found", character_id=character_id)
```

代表文件：`app/tasks/character_task.py:73`、`app/tasks/shot_task.py:72`、`app/tasks/full_generation_task.py:80,117,625`、`app/api/deps.py:54`。

同类模式在 37 个文件里重复，**按模块分批**：`api/` → `tasks/` → `agent/` → `services/`，每批收尾跑闸门。

### 2.2 status_detail 中文状态值

这些值**直接进 UI**（前端 `shot.status_detail` 会渲染）：

- `app/agent/tools/save_tools.py:132,222,325,424` —— `"等待重新生成图片"` 等
- `app/tasks/step8_video_gen_task.py:1052,1290` —— `f"提示词生成失败: {e}"`、`f"积分不足: {e}"`

改为**结构化状态码**而非英文句子，让前端自己渲染文案：

```python
shot.status_detail = {"code": "awaiting_image_regeneration"}
```

> ⚠️ `status_detail` 目前混用 str 和 dict（`save_tools` 写 str，`step8` 写 dict 的 key）。本轮统一成 dict，需同步改前端读取处，并在迁移里处理存量。

---

## Phase 3 — Prompt 英文化（主体工作量 + 最高风险）

8602 行 prompt。**必须分两类对待，但两类都要改英文**（已确认决策）。

### 3.1 语言路由机制

改造 `read_prompt_file()`（`app/utils/file_utils.py:72`）：

```python
def read_prompt_file(filename: str, locale: str = "en") -> str:
    # 优先 app/prompt/{locale}/{filename}，回退 app/prompt/{filename}
```

目录结构：
```
app/prompt/
├── en/          # 新增，英文版（默认）
│   ├── character_analysis.md
│   └── ...
└── zh/          # 现有文件迁入，保留
```

**同时收口 `app/utils/ai_client.py:2999`** 那条绕过 `read_prompt_file()` 的内联加载路径——否则改了也是漏的。
`app/agent/prompts/loader.py:15` 同样处理（注意它要保留 YAML 头解析 + Jinja2 渲染）。

### 3.2 A 类：生成用户可见内容（优先，风险低）

直接决定用户看到什么，**必须英文**：

`character_analysis.md`、`character.md`、`scene_decomposition.md`、`shot_decomposition_V3.md`、`agent_generate_character.md`、`agent_generate_scene.md`、`agent_generate_shot.md`

改动要点：
- 「输出中文提示词」→ 「Output in English」
- **输出 JSON 的键名同步改英文**（与 Phase 4 的契约变更对齐，两者必须同批发版）
- 默认角色名 `旁白` → `Narrator`
- `character.md` 末行「请将生成的**中文**提示词放在 `<提示词>` 标签内」——注意 `character_task.py:144`
  正是用 `re.search(r"<提示词>(.*?)</提示词>")` 提取的，改标签要两边同步，否则提取失败会静默回落到整段 LLM 输出

> ⚠️ **`character_analysis.md` 和 `shot_decomposition_V3.md` 不要在本节改**——这两份的改动与角色标识体系强耦合，
> 统一放到 Phase 3.5 一次改完，避免改两遍。
>
> ⚠️ **注意版本号**：`ai_client.py:834` 硬编码加载的是 `shot_decomposition_V3`。
> `shot_decomposition_V2/V4/new.md` 全仓**无任何代码引用**（已 grep 确认），是死文件。
> 本轮建议直接删除，不要翻译——留着以后切版本必然踩「改过的版本没在跑」的坑。

### 3.3 B 类：生成喂给豆包的 image/video prompt（高风险）

`shot_image*.md`(5)、`scene_image*.md`(2)、`video_generation_v*.md`(5)、`video_prompt_builder*.md`(2)、`agent_video_prompt_gen.md`、`image_prompt_formula.md` 等 17 份。

**风险说明（务必让业务方知情）**：生图/生视频模型是 `doubao-seedream-5-0` 和 `doubao-seedance-2-0`（火山引擎），中文模型对中文 prompt 的理解通常更准。改英文后可能出现画质下降、风格漂移、角色一致性变差。

**做法**：
1. 逐份翻译，**保留 prompt 结构与专业术语**（运镜、景别、光影等术语用行业标准英文，不要直译）
2. 用 Phase 0.3 的 3 篇基线小说重跑，与基线**逐图对比评分**
3. **质量不达标就回滚该份 prompt 到中文**——`read_prompt_file` 的回退机制天然支持混合：`app/prompt/en/` 下没有的文件自动回退到中文版

> 这条回退机制是本 Phase 的安全阀：允许 A 类全英文、B 类中个别效果差的先留中文，而不是全有或全无。

### 3.4 清掉硬性中文指令

7 处显式要求：`agent_video_prompt_gen.md:125`、`agent_generate_character.md:205`、`agent_generate_shot.md:411,418`、`agent_generate_scene.md:213`、`regenerate_shot_both.md:130`、`scene_image_v2.md:61`

---

## Phase 3.5 — 角色标识体系重构（决策 4/5/6 的落地）

> **状态：3.5.1 – 3.5.6 + 3.5.8 已实现**（2026-09-02）。
> 3.5.7（narration 键名 `角色`/`内容` → `role`/`content`）仍留给 Phase 4——
> 本轮只在 narration item 上**新增** `character_id`，中文键保持不变，前端 narration 相关代码不动。
> 未验证项：Alembic 迁移未在真实库上跑过（本地无可用 DB），端到端生成未跑。

单纯把 prompt 翻成英文**不够**。角色名今天同时承担三个职责：显示名、变体区分键、跨模块匹配键。
第三个职责在中文下靠子串匹配勉强能跑，换成英文名就会误匹配，且**失败时静默降级不报错**。

本 Phase 把三个职责拆开：`name` 只负责显示，变体靠结构化字段区分，跨引用一律用 `character_id`。

### 3.5.1 Character 模型加结构化字段

`app/models/character.py` 新增 4 列：

| 列 | 类型 | 取值 |
|---|---|---|
| `age_group` | `String(20)` nullable | `child`(0-12) / `teen`(13-17) / `youth`(18-35) / `middle_aged`(36-55) / `elder`(56+) |
| `state` | `String(120)` nullable | 英文短名词短语，小写：`drenched` / `formal attire` / `injured` / `taoist robes` / `battle-ready` / `transformed`。日常状态为 `null` |
| `character_type` | `String(20)` not null, default `on_screen` | `on_screen` / `voice` |
| `voice_channel` | `String(20)` nullable | 仅 voice：`phone` / `intercom` / `memory` / `distant` / `offscreen` |

`name` 从此**只存人名或身份称呼**——`Zhou Yu`、`Homeroom Teacher`、`Mother`。

> 附带好处：`name` 是 `String(100)`，原先担心英文三段名撑爆长度，现在只存人名反而比中文全名更短，该顾虑消失。

Alembic 迁移（仿 `xxxx001_add_voice_fields.py` 的写法）：
- `op.add_column` × 4，`character_type` 带 `server_default='on_screen'`
- backfill 一句：`UPDATE characters SET character_type='voice' WHERE basic_info='声音角色'`
- `downgrade()` 直接 `drop_column` × 4

**这条 backfill 是列语义搬迁，不是文案翻译**——决策 6 说的「存量不迁移」指不翻译老角色名，
但 `basic_info='声音角色'` 这个哨兵必须搬进 `character_type`，否则老数据的声音角色会被当成出镜角色去生图、白烧积分。

同步改 `app/schemas/character.py`：`CharacterBase` / `CharacterUpdate` / `Character` 三处都加这 4 个字段。

### 3.5.2 `character_analysis.md` 重写：结构化输出 + 音译规范

**输出从「按角色名做键的字典」改成「数组」**——这一步直接消灭「名字即键」的模式：

```json
{
  "chapter_info": { "chapter_number": "...", "title": "...", "word_count": ... },
  "characters": [
    {
      "name": "Zhou Yu", "character_type": "on_screen",
      "age_group": "teen", "state": "school uniform",
      "basic_info": "...", "appearance": "...", "body": "...",
      "hair": "...", "clothing": "...", "tags": "...", "voice_description": "..."
    },
    {
      "name": "Homeroom Teacher", "character_type": "on_screen",
      "age_group": "middle_aged", "state": null, "...": "..."
    },
    {
      "name": "Mother", "character_type": "voice",
      "voice_channel": "phone", "voice_description": "..."
    }
  ]
}
```

**音译规范**（写进 prompt，配示例）：

| 输入类型 | 规则 | 示例 |
|---|---|---|
| 中文人名 | 汉语拼音，姓名之间空格，各段首字母大写，名连写不加连字符 | `周宇` → `Zhou Yu`；`陶未` → `Tao Wei`；`欧阳峰` → `Ouyang Feng` |
| 姓 + 职务/敬称 | 意译，职务在前 | `李总` → `Director Li`；`王老师` → `Teacher Wang`；`张医生` → `Doctor Zhang` |
| 纯身份称呼 | 直接意译 | `班主任` → `Homeroom Teacher`；`旁白` → `Narrator`；`远处路人` → `Distant Passerby` |
| 已有英文名 | 原样保留 | — |

**跨章节一致性**：同一汉字串必须给出同一 romanization。
`creation_task.py:141-144` 已经把 `historical_characters` 传进去了，prompt 里要明写「优先复用历史角色库中已有的英文名」。
注意 `historical_characters` 目前也是**按 `char.name` 做键的字典**（`creation_task.py:137`），一并改成数组。

prompt 里原有的 30+ 处中文示例名、年龄段枚举、临时状态词表、声音状态词表全部按上表重写。
**「所有角色名必须带状态标识」那整套命名规范删掉**——状态现在是字段，不是名字的一部分。

### 3.5.3 落库改造：变体去重键

`creation_task.py:176-261` 的去重查询从 `Character.name == char_name` 改成三元组：

```python
existing = db.query(Character).filter(
    scope_filter,                                   # creation_id 或 novel_id，逻辑不变
    Character.name == c["name"],
    Character.age_group == c.get("age_group"),
    Character.state == c.get("state"),
    Character.deleted_at.is_(None),
).first()
```

同一人物的多个外观状态因此仍是多行（`Zhou Yu` + `teen` + `school uniform` / `Zhou Yu` + `teen` + `drenched`），
但 `name` 相同——这正是想要的：FE 能按人聚合，后端能按变体区分。

出镜/声音两段循环（`:176-261`）合并成一次遍历，靠 `character_type` 分流，
不再需要 `basic_info="声音角色"` 这个哨兵。

加一个纯派生的展示助手（**只用于日志和 prompt 注入，绝不作为匹配键**）：

```python
@property
def variant_label(self) -> str:          # "Zhou Yu (teen, school uniform)"
    parts = [p for p in (self.age_group, self.state) if p]
    return f"{self.name} ({', '.join(parts)})" if parts else self.name
```

### 3.5.4 跨引用改用 `character_id`（本 Phase 的核心）

角色在分镜拆解**之前**就已落库（`creation_task.py:854` 按 `creation.character_ids` 查回），
所以 `character_id` 在拆解时是现成的。把字符串匹配整条链路换成整数查表：

**注入端** `ai_client.py:836-839`：

```python
character_list_str = "\n".join(
    f"- id={c.character_id} | {c.name} | {c.character_type} | {c.age_group or '—'} | {c.state or '—'}"
    for c in characters
)
```

**输出端** `shot_decomposition_V3.md`：

| 现状 | 改为 |
|---|---|
| `"出镜角色": ["林小雨-青年"]` | `"on_screen_character_ids": [42]` |
| `"声音角色": ["教授-中年"]` | `"voice_character_ids": [17]` |
| `"台词": [{"角色": "林小雨-青年", "内容": "..."}]` | `"narration": [{"character_id": 42, "content": "..."}]` |

prompt 里「必须使用角色特征库中的完整名称（包含状态）」那条规则（`:45`）改成
「必须使用上表给出的 `id`，禁止输出角色名」。

**消费端** `creation_task.py:988-1000`——**删掉子串模糊匹配**：

```python
# 删除：if name in db_char_name or db_char_name in name
char_by_id = {c.character_id: c for c in characters}
for cid in shot_data.get("on_screen_character_ids", []):
    char = char_by_id.get(cid)
    if char:
        shot.characters.append(char)
    else:
        logger.warning(f"分镜 {shot_number} 引用了不存在的 character_id={cid}")
```

> 保留一轮按 name 的兜底分支并打 warning——**这是发版窗口期的 Celery 存量 payload 兼容**（队列里可能有旧格式任务），
> 与决策 6 的「存量数据不迁移」是两码事。下个版本移除。

**音色映射端** `audio_tools.py:280-312`、`narration_audio_tagger.py:137-160`：
`char_voice_map` 从按 `speaker` 名字做键改成按 `character_id` 做键。
这两处今天是**精确匹配 + 匹配不上静默回落默认旁白音色**，是最容易漏测的坑——
改 ID 之后，回落分支要打 warning，不能再无声吞掉。

### 3.5.5 删除 `character_state_identifier.py`

整个模块的职责（从中文描述文本里猜状态）被 `state` 字段取代，直接删。

调用方 `step7_video_prompt_gen_task.py:122-160`、`step8_video_gen_task.py:586-620` 改成直读字段：

```python
characters.append({
    "name": char.name,
    "age_group": char.age_group,
    "state": char.state,
    "appearance": appearance_full,
})
```

> 🔥 **顺带修掉一个现存 bug**：这两处都写 `basic_info = char.basic_info if isinstance(char.basic_info, dict) else {}`
> （`step7:128`、`step8:592`），但 `Character.basic_info` 是 `String(500)`，**永远不是 dict** →
> `age_group` 恒为 `'未知'` → 现在喂给视频模型的角色标识实际是 `周宇-未知`。
> 改用真字段后这个 bug 自然消失，但值得单独在 PR 描述里点出来——它现在正在影响线上生成质量。

### 3.5.6 声音角色判定收口

`basic_info == "声音角色"` 这个字符串哨兵三处写读，全部换成 `character_type`：

| 位置 | 现状 | 改为 |
|---|---|---|
| `creation_task.py:253` | 写 `basic_info="声音角色"` | 写 `character_type="voice"` |
| `creation_task.py:881` | 读 `if char.basic_info == "声音角色"` | `if char.character_type == "voice"` |
| `shot_task.py:114` | 同上（跳过声音角色不生图） | 同上 |
| FE `character-setting.tsx:526-527` | `c.body !== null` / `c.body === null` | `c.character_type === 'on_screen'` / `=== 'voice'` |

注意前后端今天判定口径就**不一致**（后端看 `basic_info`，前端看 `body`），本节一并统一。

### 3.5.7 narration 契约（与 Phase 4 合并发版）

最终形态——在 Phase 4.1 的键名英文化基础上再加 `character_id`：

```json
[{"character_id": 42, "role": "Zhou Yu", "content": "..."}]
```

- `role` 是**反规范化的展示名**，FE 直接渲染，不用回查角色表
- 音色映射以 `character_id` 为准；`character_id` 为 `null` 时按 `role` 兜底
- 旁白：`{"character_id": null, "role": "Narrator", "content": "..."}`

### 3.5.8 前端联动

- `src/types/character.ts` 的 `ICharacter` 加 `age_group` / `state` / `character_type` / `voice_channel`
- `character-setting.tsx:526-527` 分组改按 `character_type`（见 3.5.6）
- `character-setting.tsx:731` 硬编码的 `声音角色` → `t('voiceCharacters')`（key 已存在，`zh.json:1110`）
- 角色卡片渲染：`name` 为主标题，`age_group` 渲染成 badge（走 i18n，新增 5 个 key：
  `characterAgeGroup.child|teen|youth|middleAged|elder`），`state` 是 LLM 产出的英文自由文本，**原样渲染不走 i18n**
- 老 creation 的中文角色名（决策 6：不迁移）此时 `age_group`/`state` 均为 `null`，
  卡片只显示 `name` 即原来的 `周宇-少年-校服`——**这是可接受的降级，但要确认 UI 不会因缺 badge 而错位**

---

## Phase 3.6 — 中文关键词表与硬编码标签

这些不是 prompt，也不是报错，但同样直接影响英文产出质量。散落在 Phase 2/3 之间容易漏，单列一节。

| 位置 | 问题 | 处理 |
|---|---|---|
| `audio_tools.py:150-170` `_analyze_emotion` | 情感关键词表纯中文（开心/难过/生气…）→ **英文台词下所有对话恒判 `neutral`**，情感标签与语速全丢 | 换英文关键词表，或改由 LLM 打标 |
| `narration_audio_tagger.py:156` | `[..., " narrator"]` 前导空格 typo，这个分支永远匹配不上 | 修掉，并统一加入 `"Narrator"` |
| 默认说话人 `旁白` → `Narrator`（12 处） | `creation_task.py:959`、`step7:100/104/108/112`、`step8:564/568/572/576`、`audio_tools.py:150/302`、`narration_audio_tagger.py:85/156`、`db_tools.py:1547/1601`、`audio_engineer.py:86`、`storyboard_director.py:86/147` | 统一常量，别再各处写字面量 |
| `STYLE_MAPPING`（`character_task.py:28`、`step4_scene_image_gen_task.py:29`） | 5 种风格描述全中文，直接拼进生图提示词 | 翻英文；两份内容近乎重复，建议提取到公共模块 |
| `CHARACTER_NORM_PROMPT`（`character_task.py:37-42`） | 中英混写，首句中文与后面的英文语义重复 | 删中文半句 |
| `character_task.py:113-121` | `character_features` 的字段标签硬编码中文（"角色姓名："/"容貌特征："…），直接进 LLM 输入 | 翻英文 |
| `shot_task.py:120-131` | `character_profiles` 同上（"姓名: "/"外貌: "…） | 翻英文 |
| `db_tools.py:1094`、`resource_resolver.py:179/181` | 默认名 `"未命名"` | → `"Unnamed"` |
| `resource_resolver.py:140-142, 276-286` | agent 资源匹配的 system prompt 示例名全中文（"幽影-青年"），后缀剥离写死 `"的图片"/"的提示词"` | 翻英文；示例名同步换成 3.5.2 的命名规范 |

---

## Phase 3.7 — 场景分析英文化

> **状态：已实现**（2026-09-02）。未验证项：端到端未跑（本地无 DB/Celery），仅 `py_compile` 通过。
> 场景图提示词链路（`scene_image*.md` / `regenerate_scene.md` / `STYLE_MAPPING`）**本轮不动**，
> 属于 Phase 3 的 B 类高风险，需基线图对比后单独发版——见下方「本轮未做」。

角色英文化（3.5）之后，场景分析仍全中文输出：卡片标题 `学校教学楼内的班级教室`、
副标题 `安静、规整… | 日间`，分别是 `scene.title` / `scene.atmosphere` / `scene.time_setting`。
根因与角色那轮同构——**prompt 全中文 + JSON 契约用中文键**，LLM 跟着中文输出。

### 3.7.1 契约变更

`scene_decomposition.md` 全文重写为英文，输出契约：

| 现状 | 改为 |
|---|---|
| `场景列表` | `scenes` |
| `场景编号` / `场景标题` | `scene_number` / `title` |
| `环境设定` | `environment` |
| `时间` / `地点` / `氛围` | `time_setting` / `location` / `atmosphere` |
| `空间描述` / `背景元素` | `space_description` / `background_elements` |
| （无） | `space_type`（新增，见 3.7.2） |
| `文案信息` | `text_info` |

枚举值同步收紧：`time_setting` ∈ {`day`, `night`, `dawn`, `dusk`}，`space_type` ∈ {`indoor`, `outdoor`}。
prompt 里补了「字段留在源语言」的反例（拿截图里的实际错误输出当反例）。

消费端 `creation_task.py:506,526-570` 按英文键解析。

### 3.7.2 顺带修掉 `space_type` 的列语义错位

`scenes.space_type` 列注释是「室内/室外」（`scene.py:23`），但 `creation_task.py:556` 实际塞的是
`space_description[:50]`——一段被截断的布局描述。老 prompt 根本没让 LLM 输出空间类型。

本轮 prompt 新增 `space_type` 枚举字段，落库存真值；布局描述只进 `extra_data.space_description`。

**连带补丁（必须同批）**：两处注入生图 prompt 的 `"空间"` 字段原先读 `scene.space_type`，
改完后会从「一段布局描述」缩水成一个 `indoor`，画面细节会掉。改成优先读 `extra_data.space_description`：

- `step4_scene_image_gen_task.py:250-257`
- `shot_task.py:242-251`

同时给所有落库字段按列宽逐个截断（`title[:200]` / `time_setting[:50]` / `location[:200]` /
`space_type[:50]` / `atmosphere[:100]`），并用 `or ""` 兜 LLM 输出 `null`——
英文文本比中文长，原先只截 `space_type` 一个字段不够。

### 3.7.3 场景 → 分镜注入链路

场景以英文键注入分镜 prompt，分镜输出端同步改：

| 位置 | 改动 |
|---|---|
| `creation_task.py:801-815` | 注入端改英文键，额外注入 `space_description` |
| `shot_decomposition_V3.md:17-21` | 「场景信息」段说明改为列出英文字段名 |
| `shot_decomposition_V3.md:36-38` | 要求输出 `scene_number`（整数）+ `scene_title`（原样复制，不改写不翻译） |
| `shot_decomposition_V3.md:111-126` | 输出示例的 `场景编号`/`场景标题` → `scene_number`/`scene_title` |
| `creation_task.py:878-892` | 读取端改英文键 |
| `ai_client.py:690,851` | 日志键 + `场景内容` 剔除逻辑 |

> 🔥 **顺带修掉一个静默降级**：`creation_task.py:883` 原先要求 `isinstance(scene_idx, int)`，
> 而 prompt 示例给的是字符串 `"1"`。字符串编号会跳过 ID 匹配、掉进 title 匹配，
> title 再匹配不上就掉进 `:888` 的「兜底关联到第一个场景」——**所有分镜挂到场景 1，只打一条 warning**。
> 现已统一 `int()` 强转。与 3.5.4 删掉的角色子串模糊匹配是同类坑。

**本节与 3.7.1 必须同批发版**：注入端与读取端都已改英文键，未留中文兜底
（`scene_result` 是同一任务内现调 LLM 拿的，不存在 Celery 旧 payload 问题；
但分两次发版会导致中间态全部掉进兜底关联）。

### 3.7.4 Agent 模式独立链路

`script_analyst.py` 是 Agent 模式下的场景/角色提取，与主流程 prompt 完全独立，
容易漏。SYSTEM_PROMPT（`:41-81`）全文翻英文：

- 枚举值对齐 3.7.1：`indoor|outdoor`、`day|night|dusk`
- `atmosphere` 长度约束从「20 字以内」改为「100 字符以内」（对齐列宽，英文更长）
- 补人名罗马化 + 地名意译规则，与 `character_analysis.md`（3.5.2）保持一致
- `get_user_message`（`:98`）的中文提示语一并改

`agent_generate_scene.md:213` 已在 commit `1faa116`（Phase 3.4）改为 English prompt，本轮无需再动。

### 3.7.5 前端

**无需改动**。已确认 `mira-fe/src/` 只有 `lib/mock-data/*.json` 含中文场景值，
无任何按 `室内`/`日间` 做的枚举判断或分支，场景字段全部原样渲染。

### 3.7.6 本轮未做（留给 Phase 3 B 类）

场景图提示词链路仍产出中文，**这是独立问题，不影响场景卡片显示**——
它生成的是 `scene.extra_data["image_prompt"]`，用户在 `scene-edit-modal.tsx:43`
和 `scene-detail-dialog.tsx:77` 能看到并编辑：

| 位置 | 问题 |
|---|---|
| `scene_image.md:1,69`、`regenerate_scene.md:25,78` | 明写「生成用于生成场景环境图的**中文**提示词」 |
| `step4_scene_image_gen_task.py:264` | `{output_language}` 写死 `"中文"` |
| `step4_scene_image_gen_task.py:29-35` `STYLE_MAPPING` | 5 种风格描述全中文，直接拼进生图提示词（`character_task.py:28` 有重复副本，见 3.6） |

改这些需要 Phase 0.3 的基线图对比，效果不达标要能单独回滚，故不与本轮混在一个 PR。

### 3.7.7 验收

1. 传英文小说 → 场景卡片 `title` / `atmosphere` / `time_setting` 全英文，
   `time_setting` 显示 `day`/`night` 而非 `日间`
2. `grep -rn "场景列表\|场景标题\|环境设定" app/ --include=*.py` 仅剩注释/docstring
3. **分镜关联场景 100% 命中**：全流程日志中 `分镜无法关联到场景` 应为 0 条（验证 3.7.3 的强转修复）
4. `scenes.space_type` 落库值为 `indoor`/`outdoor`，不再是被截断的布局描述（验证 3.7.2）
5. 生成一轮场景图，确认注入的 `"空间"` 字段是布局描述而非单词 `indoor`（验证连带补丁）
6. **跨章节复用**：同一部小说跑第二章，同名同 `location` 同 `time_setting` 的场景应复用而非重复建档
7. Agent 模式走一遍剧本分析，场景/角色输出同样全英文（验证 3.7.4 这条独立链路）

### 3.7.8 已知边界

**存量场景与新场景混跑会重复建档**。`creation_task.py:539` 的复用键是
`f"{title}|{location}|{time_setting}"`，老数据是 `班级教室|…|日间`，新数据是 `Classroom|…|day`，
同一场景跑第二章必然新建。这是决策 6「存量不迁移」的既定代价，与「已知边界」里
角色音译一致性问题同源。验收项 6 只覆盖**新建 creation 内部**的跨章节复用。

---

## Phase 4 — 数据契约英文化（破坏性变更）

已确认本轮做，带数据迁移。**必须与前端同步发版。**

### 4.1 契约变更

| 现状 | 改为 |
|---|---|
| `{"角色": "...", "内容": "..."}` | `{"character_id": 42, "role": "...", "content": "..."}` |
| `"出镜角色"` / `"声音角色"` | `"on_screen_character_ids"` / `"voice_character_ids"`（值从名字数组变成 ID 数组） |
| 默认值 `"旁白"` | `{"character_id": null, "role": "Narrator"}` |

> 与原计划的差异：因为决策 5，`出镜角色`/`声音角色` 不只是**改键名**，**值的类型也变了**（名字 → ID）。
> 具体见 Phase 3.5.4 和 3.5.7，这两个 Phase 必须同一批发版。

涉及 15 个文件、103 处引用。代表位置：`app/tasks/creation_task.py:863,864,959,986,1007`、`app/agent/tools/db_tools.py:1547,1601,1602`、`app/agent/tools/narration_audio_tagger.py:85,137,149`、`app/tasks/shot_task.py:114,167`、`app/tasks/step7_video_prompt_gen_task.py:102`、`app/tasks/step8_video_gen_task.py:566`。

### 4.2 数据迁移

存量数据在 `shot.narration`（`app/models/shot.py:29`，**Text 字段存 JSON 字符串**）。

新增 Alembic 迁移：
- 遍历所有 `shot` 行，解析 narration JSON，键名 `角色`→`role`、`内容`→`content`，值 `旁白`→`Narrator`
- 同样处理 `creation.extra_data` 里的 `出镜角色`/`声音角色`
- **必须实现 `downgrade()`**（反向映射），且迁移前备份
- 分批 commit，避免大表长事务

**`character_id` 不回填**（决策 6）：老 narration 的 `role` 值是中文角色名（如 `陶未-青年`），
迁移只把键名改成 `role`/`content`，`character_id` 留空。
音色映射的 `role` 字符串兜底分支（Phase 3.5.4）正是为这批数据留的，**不能删**。

### 4.3 过渡期读兼容

即便做了迁移，**代码里的读取处仍保留一轮兼容**：

```python
role = item.get("role") or item.get("角色") or "Narrator"
character_id = item.get("character_id")          # 老数据为 None，走 role 兜底
```

理由：Celery 队列里可能有迁移前入队的任务，携带旧格式 payload。**键名兼容**在下个版本移除。

⚠️ 但 `character_id is None` 时按 `role` 查音色的**值兜底**不能一起移除——
决策 6 下老 creation 永远没有 `character_id`（见 4.2 与「已知边界」）。
这两种兼容代码务必分开注释清楚，否则下轮清理会误删。

### 4.4 前端联动

`mira-fe` 有 **14 个文件**打了 `i18n-ignore-file` 标记专门等这个契约。本 Phase 完成后：
- 摘掉这些标记，把 `item.内容` 改成 `item.content`
- 涉及 `types/index.ts`、`types/scene.ts`、`shot-item.tsx`、`timeline.tsx`、`shot-edit-modal.tsx`、
  `storyboard-edit-modal.tsx`、`narration-edit-bottom-sheet.tsx`、`video-generator.tsx`、
  `storyboard-images.tsx`、`canvas-storyboard-view.tsx`、`canvas-character-view.tsx`、`shot-detail-dialog.tsx`
  （`mock-video-data.ts` 与 `flow-manager.ts` 两处标记与本契约无关，保留）
- **前后端必须同批发版**，否则新前端读旧后端（或反之）会拿不到 narration
- 渲染 narration 时优先用 `item.role`；老数据 `character_id` 为 `null` 是正常的，不要据此判空

---

## Phase 5 — voices 端点与其它

- `app/api/api_v1/endpoints/voices.py:24` 默认值 `zh` → `en`（依赖 Phase 0.1 验证结果）
- 该文件的 Query description 也是中文，一并改（这些会进 Swagger 文档，对外可见）
- 全量扫 `app/api/` 下所有 `summary=` / `description=` 中文（Swagger 是对外文档）

---

## 验收

```bash
python scripts/check_zh.py          # Phase 0 的闸门，残留应为 0（白名单外）
pytest tests/ -v                    # 现有测试
alembic upgrade head && alembic downgrade -1 && alembic upgrade head   # 迁移可逆性

# Phase 3.5 完成后应全部无输出（除注释/文档）
grep -rn "in db_char_name" app/                        # 子串模糊匹配已删除
grep -rn "character_state_identifier" app/             # 模块已删除
grep -rn '"声音角色"' app/ --include=*.py               # 哨兵已换成 character_type
```

**端到端人工验收**（对着 3 篇基线小说）：

1. 上传小说 → 剧本 → 角色 → 场景 → 分镜 → 视频，**全程产出应为英文**
2. **生成质量对比**：与 Phase 0.3 基线逐图评分，画质/一致性不得明显下降
3. 旁白英文 + 英文音色，**试听确认发音正常**
4. 制造各类错误（404 / 权限 / 积分不足 / 文件过大），确认响应含 `code` 字段且 `message` 为英文
5. 前端 `shot-detail-dialog` 里 narration 正常显示与编辑（验证契约变更 + 前端联动）
6. 老数据（迁移前创建的 creation）打开后 narration 正常——验证迁移与读兼容

**角色标识体系专项验收**（Phase 3.5）：

7. 角色名全英文、**不含 `-年龄段-状态` 后缀**；`班主任` 这类身份称呼已意译为 `Homeroom Teacher`
8. 同一人物的多个外观状态 → 多行角色，`name` 相同、`state` 不同（如 `Zhou Yu` × `school uniform` / `drenched`）
9. **分镜关联角色 100% 命中**：全流程日志中 `未找到角色` / `引用了不存在的 character_id` 应为 0 条
10. **音色不静默降级**：每条 narration（除 Narrator）都解析到 `character_id` 并用上该角色的 `voice_id`，
    回落默认音色的 warning 应为 0 条
11. **跨章节复用**：同一部小说跑第二章，同名同状态角色应复用而非重复建档
    （英文名不一致会导致重复，这是音译规范最容易翻车的地方）
12. **视频提示词里的角色标识不再出现 `未知`**（验证 3.5.5 修掉的 bug）
13. 老 creation（中文角色名、`age_group`/`state` 为 `null`）打开后角色卡片不错位

---

## 顺序与依赖

```
Phase 0 (验证音色 + 闸门 + 质量基线)   ←── 阻塞项，必须先做
   ↓
Phase 1 (i18n 基础设施)
   ↓
Phase 2 (报错/状态值)                 ←── 独立，可与 Phase 3 并行
   ↓
Phase 3 (Prompt 英文化)               ←── 主体工作量，B 类需质量回归
   ↓
Phase 3.5 (角色标识体系)  ┐
Phase 3.6 (关键词表/标签)  │           ←── 3.6 独立，可与 3.5 并行
Phase 3.7 (场景分析)       │           ←── 独立，已完成；场景图 prompt 留在 Phase 3 B 类
   ↓                      │
Phase 4 (数据契约 + 迁移) ┘           ←── 3.5 与 4 必须同一批发版
   ↓
Phase 5 (voices / Swagger)
```

**Phase 3 的 B 类、Phase 3.5 + 4 建议各自独立 PR**：
- Phase 3 B 类 → 挂生成质量对比结果
- Phase 3.5 + Phase 4 → 合成一个 PR（契约变更 + 模型变更 + 前端联动同批），挂迁移验证与专项验收 7-13 的结果

混在一起没法 review。

### Phase 3.5 内部顺序

3.5.1（模型 + 迁移）必须最先——后面所有步骤都依赖新字段存在。
之后 3.5.2（prompt）与 3.5.3（落库）绑定改，3.5.4（ID 引用）依赖 3.5.3 已经能正确落库。
3.5.5 / 3.5.6 是清理，随时可做。3.5.7 / 3.5.8 与 Phase 4 一起收尾。

---

## 已知边界（本计划不覆盖）

- **存量角色名不翻译**（决策 6）：迁移前创建的 creation，角色名保持 `周宇-少年-校服` 形态，
  `age_group`/`state` 为 `null`。这些老 creation 继续走 `role` 字符串兜底路径，音色映射可能不准。
  如果后续要处理，是独立一轮工作（人名翻译无法机械映射，只能靠 LLM 重跑角色分析）
- **存量场景名不翻译**（决策 6 的同源问题）：迁移前创建的场景，`title`/`atmosphere`/`time_setting`
  保持中文形态。场景复用键含 `title` 与 `time_setting`，故中英混跑期同一场景会重复建档。
  详见 Phase 3.7.8
- **音译一致性无自动校验**：同一汉字串在不同章节被 LLM 译成不同英文名（`Zhou Yu` vs `Zhouyu`）
  会导致重复建档。本轮只靠 prompt 里「优先复用历史角色库」约束 + 验收项 11 人工检查，
  没有做 romanization 归一化校验
- **前端遗留**：27 处缺失 key 仍渲染 key 路径（标签/占位，已决定保留）；e2e 测试未适配英文化（前端 Phase 5 已跳过）
- **法务**：`terms`/`privacy` 缺 GDPR/CCPA、无 cookie 同意、年龄门槛 13 岁
- **Supabase 邮件模板**：在控制台配置，不在任何仓库里，需人工去 Dashboard 改英文
- **`mira-fe` 未跑过 `pnpm build`**：合并前建议补跑一次
