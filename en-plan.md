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

### 已确认的三个决策

1. **image_prompt / video_prompt 也改英文**——用户在 `shot-detail-dialog` 里能看到并编辑它们，体验要统一。
   ⚠️ **这是本计划最大的技术风险**，见 Phase 3。
2. **数据契约本轮就改**，带 Alembic 数据迁移，前后端同步发版。
3. **TTS 英文音色库情况未知**，计划第一步先验证。

### 关键杠杆点（复用现有代码，不另起炉灶）

| 位置 | 作用 |
|---|---|
| `app/utils/file_utils.py:72` `read_prompt_file()` | **prompt 加载唯一主入口**，语言路由改这里 |
| `app/utils/ai_client.py:2999` | 第二条 prompt 加载路径，需一并收口 |
| `app/agent/prompts/loader.py:15` `load_prompt()` | agent prompt 加载器（带 YAML 头 + Jinja2） |
| `app/core/exceptions.py` | 13 个异常类的干净继承体系，**错误码就加在这里** |
| `app/middleware/error_handler.py` | 3 个全局处理器，响应格式统一收口点 |
| `alembic/versions/` | 53 个已有迁移，数据迁移基础设施现成 |

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

`character_analysis.md`、`character.md`、`scene_decomposition.md`、`shot_decomposition_V4.md`、`agent_generate_character.md`、`agent_generate_scene.md`、`agent_generate_shot.md`

改动要点：
- 「输出中文提示词」→ 「Output in English」
- **输出 JSON 的键名同步改英文**（与 Phase 4 的契约变更对齐，两者必须同批发版）
- 默认角色名 `旁白` → `Narrator`

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

## Phase 4 — 数据契约英文化（破坏性变更）

已确认本轮做，带数据迁移。**必须与前端同步发版。**

### 4.1 契约变更

| 现状 | 改为 |
|---|---|
| `{"角色": "...", "内容": "..."}` | `{"role": "...", "content": "..."}` |
| `"出镜角色"` / `"声音角色"` | `"on_screen_characters"` / `"voice_characters"` |
| 默认值 `"旁白"` | `"Narrator"` |

涉及 15 个文件、103 处引用。代表位置：`app/tasks/creation_task.py:863,864,959,986,1007`、`app/agent/tools/db_tools.py:1547,1601,1602`、`app/agent/tools/narration_audio_tagger.py:85,137,149`、`app/tasks/shot_task.py:114,167`、`app/tasks/step7_video_prompt_gen_task.py:102`、`app/tasks/step8_video_gen_task.py:566`。

### 4.2 数据迁移

存量数据在 `shot.narration`（`app/models/shot.py:29`，**Text 字段存 JSON 字符串**）。

新增 Alembic 迁移：
- 遍历所有 `shot` 行，解析 narration JSON，键名 `角色`→`role`、`内容`→`content`，值 `旁白`→`Narrator`
- 同样处理 `creation.extra_data` 里的 `出镜角色`/`声音角色`
- **必须实现 `downgrade()`**（反向映射），且迁移前备份
- 分批 commit，避免大表长事务

### 4.3 过渡期读兼容

即便做了迁移，**代码里的读取处仍保留一轮兼容**：

```python
role = item.get("role") or item.get("角色") or "Narrator"
```

理由：Celery 队列里可能有迁移前入队的任务，携带旧格式 payload。兼容代码在下个版本移除。

### 4.4 前端联动

`mira-fe` 有 **14 个文件**打了 `i18n-ignore-file` 标记专门等这个契约。本 Phase 完成后：
- 摘掉这些标记，把 `item.内容` 改成 `item.content`
- 涉及 `shot-edit-modal.tsx`、`storyboard-edit-modal.tsx`、`narration-edit-bottom-sheet.tsx`、`types/index.ts`、`types/scene.ts` 等
- **前后端必须同批发版**，否则新前端读旧后端（或反之）会拿不到 narration

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
```

**端到端人工验收**（对着 3 篇基线小说）：

1. 上传小说 → 剧本 → 角色 → 场景 → 分镜 → 视频，**全程产出应为英文**
2. **生成质量对比**：与 Phase 0.3 基线逐图评分，画质/一致性不得明显下降
3. 旁白英文 + 英文音色，**试听确认发音正常**
4. 制造各类错误（404 / 权限 / 积分不足 / 文件过大），确认响应含 `code` 字段且 `message` 为英文
5. 前端 `shot-detail-dialog` 里 narration 正常显示与编辑（验证契约变更 + 前端联动）
6. 老数据（迁移前创建的 creation）打开后 narration 正常——验证迁移与读兼容

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
Phase 4 (数据契约 + 迁移)             ←── 破坏性，需与前端同批发版
   ↓
Phase 5 (voices / Swagger)
```

**Phase 3 的 B 类和 Phase 4 建议各自独立 PR**：前者要挂生成质量对比结果，后者要挂迁移验证结果，混在一起没法 review。

---

## 已知边界（本计划不覆盖）

- **前端遗留**：27 处缺失 key 仍渲染 key 路径（标签/占位，已决定保留）；e2e 测试未适配英文化（前端 Phase 5 已跳过）
- **法务**：`terms`/`privacy` 缺 GDPR/CCPA、无 cookie 同意、年龄门槛 13 岁
- **Supabase 邮件模板**：在控制台配置，不在任何仓库里，需人工去 Dashboard 改英文
- **`mira-fe` 未跑过 `pnpm build`**：合并前建议补跑一次
