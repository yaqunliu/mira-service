# 漫剧 Agent Chat 实现重构方案

> **版本**: v1.1  
> **日期**: 2026-01-29  
> **状态**: 已确认

---

## 目录

1. [当前实现分析](#1-当前实现分析)
2. [目标架构](#2-目标架构)
3. [详细设计](#3-详细设计)
4. [文件变更清单](#4-文件变更清单)
5. [实施步骤](#5-实施步骤)
6. [验证计划](#6-验证计划)
7. [待澄清问题](#7-待澄清问题)

---

## 1. 当前实现分析

### 1.1 现有架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    /agent/chat API                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   用户消息 ─→ detect_task_intent() ─┬→ 任务意图 → Celery 任务   │
│                                     │                           │
│                                     ├→ 状态查询 → StatusHandler │
│                                     │                           │
│                                     └→ unknown → 引导回复       │
│                                                                 │
│   ※ 每个分支都直接 return，Graph 从未被调用                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│              comic_drama_graph.py (未使用)                       │
│                                                                 │
│   已实现节点：production_manager, director, script_analysis...  │
│   但从未被 /agent/chat 调用                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 核心问题

| 问题 | 描述 | 影响 |
|------|------|------|
| **Graph 未接入** | `comic_drama_graph.py` 实现了完整工作流但从未被调用 | 复杂的编排逻辑无法使用 |
| **Handler 与 Graph 分离** | `task_handler.py` 直接调用 Celery | 绕过了 LangGraph 的状态管理 |
| **意图识别独立** | 意图识别在 API 层完成 | 不是 Graph 的一部分，难以与上下文结合 |
| **状态不持久** | Graph 状态未与 Session 关联 | 无法实现断点续传 |
| **提示词硬编码** | 各 Handler 中的提示词写在代码里 | 难以调整和维护 |

### 1.3 当前代码结构

```
app/agent/
├── agents/               # Agent 团队实现
│   ├── director.py       # 导演决策（已实现）
│   ├── script_analysis_team.py
│   ├── storyboard_team.py
│   ├── audio_team.py
│   └── video_editor.py
│
├── graph/
│   └── comic_drama_graph.py  # ❌ 已实现但未被调用
│
├── handlers/             # 当前主要业务逻辑（绕过 Graph）
│   ├── task_handler.py   # 意图识别 + Celery 调用
│   └── status_query_handler.py
│
├── state/
│   ├── schemas.py        # ComicDramaState 定义
│   └── utils.py
│
└── tools/                # Agent 工具
    ├── asset_tools.py
    ├── generation_tools.py
    └── ...
```

---

## 2. 目标架构

### 2.1 设计原则

基于 `漫剧Agent产品设计文档.md` 的核心原则：

1. **对话驱动**：所有交互通过 Chat API 进入 Graph
2. **Graph 为核心**：意图识别、任务执行、状态查询都是 Graph 节点
3. **Tool 化操作**：DB 读写、图片/视频生成都封装为 Tool
4. **提示词文件化**：所有提示词以 `.md` 文件存储
5. **会话状态持久化**：Graph 状态与 AgentSession 同步

**新增核心原则**（用户确认）：

6. **API 层无业务逻辑**：API 只做 SSE 流处理，兼容同步/异步，不含任何业务判断
7. **Agent 独立闭环**：Agent 具备完整的自主能力，包括：
   - 思考（LLM 调用）
   - 执行工具（Tool 调用）
   - 消息持久化（对话记录写入 Session）
   - 调用知识库（RAG）
   - 错误重试与恢复
   - **注：业务数据（图片、视频、提示词等）的持久化由 Tool 负责，不是 Agent 的职责**

### 2.2 目标架构图

```
┌─────────────────────────────────────────────────────────────────┐
│               /agent/chat API (纯 SSE 处理)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   用户消息 ─→ Agent.run() ─→ SSE 流                               │
│                                                                 │
│   ※ API 层零业务逻辑，只做流转发，兼容同步/异步                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                 Agent 独立闭环 (LangGraph)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ╔═══════════════════════════════════════════════════════════╗   │
│   ║  思考 (LLM)  →  执行 (Tools)  →  存储 (DB)  →  知识 (RAG)  ║   │
│   ║       │                                        ↑           ║   │
│   ║       └──────────── 循环处理 ──────────────────┘           ║   │
│   ╚═══════════════════════════════════════════════════════════╝   │
│                                                                 │
│   工作流节点:                                                      │
│   entry ─→ intent_detection ─→ router ─┬─→ status_query         │
│                                       ├─→ task_execution ─→ human_review
│                                       └─→ clarify               │
│                                                 │               │
│                                                 ▼               │
│                                        response_formatter       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Tools 层                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   DB Tools:        │  生成 Tools:        │  分析 Tools:           │
│   query_*          │  generate_*        │  analyze_*            │
│   update_*         │  (封装 Celery)      │  extract_*            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 数据模型关系

```
┌────────────────────┐       ┌────────────────────┐       ┌────────────────────┐
│     Creation       │       │   AgentSession     │       │   AgentMessage     │
├────────────────────┤       ├────────────────────┤       ├────────────────────┤
│ creation_id (PK)   │◄──────│ creation_id (FK)   │       │ message_id (PK)    │
│ uuid               │       │ creation_uuid      │       │ session_id (FK)    │──►│
│ title              │  1:1  │ session_id (PK)    │  1:N  │ role               │
│ script_text        │       │ thread_id          │       │ content            │
│ ...                │       │ current_stage      │       │ message_type       │
└────────────────────┘       │ checkpoint_data    │       │ extra_data         │
                             │ user_feedback      │       └────────────────────┘
                             └────────────────────┘
```

**关系说明**:

| 关系 | 说明 |
|------|------|
| `Creation : Session = 1:1` | 每个创作项目对应一个活跃 Session |
| `Session : Message = 1:N` | 一个 Session 包含多条对话消息 |
| `thread_id` | LangGraph 的唯一标识，用于 Checkpointer 断点恢复 |
| `creation_uuid` | 冗余字段，便于通过 UUID 快速查询 |

**Session 绑定流程**:

```python
# Agent 初始化时获取或创建 Session
async def get_or_create_session(creation_uuid, user_id):
    # 1. 通过 creation_uuid 查找现有 Session
    session = await find_session_by_creation_uuid(creation_uuid)
    
    if session:
        return session  # 已存在则复用
    
    # 2. 不存在则创建新 Session
    session = AgentSession(
        creation_id=creation.creation_id,
        creation_uuid=creation_uuid,
        thread_id=str(uuid4()),  # LangGraph thread_id
        current_stage=ProductionStage.INIT,
    )
    return session
```

---

## 3. 详细设计

### 3.1 Chat API 端点重构

**文件**: `app/api/api_v1/endpoints/agent.py`

**变更前**:
```python
@router.post("/{creation_uuid}/agent/chat")
async def agent_chat(...):
    # 意图检测
    intent = await agent_task_handler.detect_task_intent(message)
    
    if is_task_intent(intent):
        # 直接调用 Celery
        await agent_task_handler.execute_single_task(...)
        return
    
    if is_status_query(intent):
        # 直接调用 StatusHandler
        async for chunk in ai_status_query_handler.generate_ai_response(...):
            yield chunk
        return
    
    # unknown - 引导回复
    async for chunk in agent_task_handler.generate_clarify_response(...):
        yield chunk
    return
    
    # ❌ Graph 代码永远不会执行
    graph = ComicDramaGraph()
    ...
```

**变更后**:
```python
@router.post("/{creation_uuid}/agent/chat")
async def agent_chat(...):
    """
    纯 SSE 处理，零业务逻辑
    兼容同步和异步调用
    """
    async def event_generator():
        # 1. 初始化 Agent
        agent = ComicDramaAgent(
            creation_uuid=creation_uuid,
            user_id=user_id,
            db_session=db
        )
        
        # 2. 运行 Agent - 所有逻辑都在 Agent 内部
        async for event in agent.run(request.message):
            yield format_sse_event(event)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**关键变化**:
- API 层零业务逻辑，只做 SSE 流转发
- Agent 内部处理所有逻辑：意图识别、任务执行、状态查询、持久化、错误重试
- 兼容同步/异步调用（Agent 内部统一处理）

---

### 3.2 Graph 节点设计

#### 3.2.1 双层架构

Graph 采用 **对话调度层 + 业务执行层** 的双层架构：

```
用户消息
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│                    对话调度层 (新增)                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   entry → intent_detection → router                             │
│                                 │                               │
│          ┌──────────────────────┼──────────────────────┐        │
│          ▼                      ▼                      ▼        │
│    status_query          task_execution            clarify      │
│          │                      │                      │        │
│          └──────────────────────┼──────────────────────┘        │
│                                 ▼                               │
│                        response_formatter                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                                  │
                                  │ 调用业务节点 / Tool
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                    业务执行层 (保留现有)                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   production_manager → asset_generation → storyboard_creation   │
│                              ↓                                  │
│         human_review ← audio_processing ← video_generation      │
│              ↓                                                  │
│           editing → completed                                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 3.2.2 两层职责对比

| 维度 | 对话调度层 | 业务执行层 |
|------|-----------|-----------|
| **定位** | 处理用户对话 | 执行创作任务 |
| **触发** | 用户消息触发 | 按创作流程推进 |
| **状态** | 短周期（单次对话） | 长周期（整个创作过程） |
| **节点来源** | 新增 | 保留现有 |

#### 3.2.3 对话调度层节点（新增）

| 节点名 | 类型 | 职责 |
|--------|------|------|
| `entry` | 入口 | 接收用户消息，初始化对话状态 |
| `intent_detection` | LLM | 识别用户意图 |
| `router` | 条件 | 根据意图路由到不同节点 |
| `status_query` | LLM + Tool | 查询状态并生成回复 |
| `task_execution` | LLM + Tool | 调度业务层节点或直接调用 Tool |
| `clarify` | LLM | 生成引导性回复 |
| `response_formatter` | 格式化 | 统一输出格式 |

#### 3.2.4 业务执行层节点（保留现有）

> ⚠️ **重要原则**：所有节点只做 **协调和决策**，不直接执行操作。  
> 具体操作必须通过 **Tool 调用** 或 **LLM 思考** 来完成。

| 节点名 | 类型 | 职责 | 调用的 Tool |
|--------|------|------|------------|
| `production_manager` | LLM | 制作管理、流程决策 | - |
| `asset_generation` | LLM + Tool | 协调角色/场景图片生成 | `generate_character_image`, `generate_scene_image` |
| `storyboard_creation` | LLM + Tool | 协调分镜创建 | `extract_shots`, `generate_shot_prompt` |
| `audio_processing` | LLM + Tool | 协调音频处理 | `generate_audio`, `generate_bgm` |
| `video_generation` | LLM + Tool | 协调视频生成 | `generate_video` |
| `editing` | LLM + Tool | 协调剪辑合成 | `merge_video`, `add_audio` |
| `human_review` | 中断 | 等待用户审核确认 | - |
| `error_handler` | LLM | 错误分析和恢复决策 | - |

#### 3.2.5 节点设计原则

```
┌─────────────────────────────────────────────────────────────────┐
│                        节点职责边界                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   节点可以做：                                                   │
│   ✅ 调用 LLM 进行思考、规划、决策                              │
│   ✅ 调用 Tool 执行具体操作                                      │
│   ✅ 更新 Graph State                                           │
│   ✅ 决定下一步流转到哪个节点                                    │
│                                                                 │
│   节点不能做：                                                   │
│   ❌ 直接调用 Celery 任务                                        │
│   ❌ 直接操作数据库                                              │
│   ❌ 直接调用外部 API（生图、生视频等）                          │
│   ❌ 包含复杂业务逻辑                                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 3.2.6 调用关系示例

```python
# ❌ 错误示例：节点直接执行操作
async def asset_generation_node_wrong(state: ComicDramaState):
    # 直接调用 Celery - 这是错误的！
    task = generate_character_image_task.delay(character_id)
    return state

# ✅ 正确示例：节点通过 Tool 执行操作
async def asset_generation_node_correct(state: ComicDramaState):
    # 1. LLM 思考：决定需要生成哪些角色
    characters_to_generate = await llm.decide_characters(state)
    
    # 2. 调用 Tool 执行生成
    for character in characters_to_generate:
        result = await generate_character_image_tool.invoke(
            character_id=character.id,
            style=state.style
        )
        state.generated_assets.append(result)
    
    # 3. 更新状态，决定下一步
    state.current_stage = "asset_generation_complete"
    return state
```

#### 3.2.6 对话调度层流转图

```
                              ┌─────────────────┐
                              │      entry      │
                              └────────┬────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │intent_detection │
                              └────────┬────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │     router      │
                              └────────┬────────┘
                                       │
            ┌──────────────────────────┼──────────────────────────┐
            │                          │                          │
            ▼                          ▼                          ▼
   ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
   │  status_query   │       │ task_execution  │       │     clarify     │
   └────────┬────────┘       └────────┬────────┘       └────────┬────────┘
            │                          │                          │
            │                          ▼                          │
            │             ┌───────────────────────┐               │
            │             │ 调用业务层 / Tool     │               │
            │             │ ↓ human_review (可选) │               │
            │             └───────────┬───────────┘               │
            │                          │                          │
            └──────────────────────────┼──────────────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │response_formatter│
                              └─────────────────┘
```

#### 3.2.3 意图识别节点详细设计

**输入**:
- `state.user_message`: 用户当前消息
- `state.messages`: 对话历史
- `state.current_stage`: 当前创作阶段

**输出**:
- `detected_intent`: 识别的意图类型
- `intent_category`: 意图分类
- `intent_details`: 意图详情（目标对象、范围等）
- `intent_confidence`: 置信度

**意图分类**:
```
task_intent (任务意图):
├── analyze_character     # 分析角色
├── analyze_scene         # 分析场景
├── analyze_shot          # 分析分镜
├── generate_character_images
├── generate_scene_images
├── generate_shot_images
├── generate_videos
└── auto_create           # 一键创作

status_query (状态查询):
├── overall_status        # 整体进度
├── character_status      # 角色状态
├── scene_status          # 场景状态
├── image_status          # 图片状态
└── video_status          # 视频状态

asset_action (资产操作):
├── modify_prompt         # 修改提示词
├── regenerate            # 重新生成
└── select_option         # 选择候选项

other:
├── confirm               # 确认
├── cancel                # 取消
├── help                  # 帮助
└── unknown               # 未知
```

---

### 3.3 Tools 设计

#### 3.3.1 Tool 分类

| 类别 | Tool 名称 | 功能描述 |
|------|-----------|----------|
| **DB 查询** | `query_characters` | 查询角色列表 |
| | `query_scenes` | 查询场景列表 |
| | `query_shots` | 查询分镜列表 |
| | `query_creation_status` | 查询创作整体状态 |
| **DB 写入** | `update_character` | 更新角色属性 |
| | `update_scene` | 更新场景属性 |
| | `update_shot` | 更新分镜属性 |
| | `update_prompt` | 更新提示词 |
| **生成类** | `generate_character_image` | 生成角色图片 |
| | `generate_scene_image` | 生成场景图片 |
| | `generate_shot_image` | 生成分镜图片 |
| | `generate_video` | 生成视频 |
| | `generate_audio` | 生成音频 |
| **分析类** | `analyze_script` | 分析剧本 |
| | `extract_characters` | 提取角色 |
| | `extract_scenes` | 提取场景 |

#### 3.3.2 Tool 与 Celery 的关系

```
Tool 调用流程:
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Graph 节点    │ ──▶ │   Tool 函数     │ ──▶ │   Celery 任务   │
│                 │     │                 │     │                 │
│ task_execution  │     │ generate_xxx()  │     │ xxx_task.delay()│
└─────────────────┘     └────────┬────────┘     └────────┬────────┘
                                 │                       │
                                 ▼                       ▼
                        返回 task_id              异步执行生成
                        更新 state                返回结果/回调
```

**说明**:
- Tool 是 Graph 节点调用的接口
- Tool 内部可以调用 Celery 任务进行异步处理
- Celery 任务保留现有实现，只是被 Tool 封装

---

### 3.4 提示词管理

#### 3.4.1 目录结构

```
app/agent/prompts/
├── __init__.py
├── loader.py             # 提示词加载器
├── intent_detection.md   # 意图识别
├── status_response.md    # 状态回复生成
├── clarify_response.md   # 引导性回复
├── task_confirmation.md  # 任务确认消息
├── script_analysis.md    # 剧本分析
└── image_prompt_generation.md  # 图片提示词生成
```

#### 3.4.2 提示词文件格式

```markdown
---
name: intent_detection
version: "1.0"
model: gpt-4o-mini
temperature: 0.3
---

# 意图识别

你是一个漫剧创作助手，需要识别用户的意图类型。

## 意图类型
...

## 输入
{{ user_message }}
{{ chat_history }}

## 输出格式
返回 JSON: { "intent": "...", "confidence": 0.0-1.0, ... }
```

---

### 3.5 SSE 事件协议

#### 3.5.1 设计原则

> ⚠️ **核心原则**：
> - 基于 **LangGraph `stream_mode="messages"`** 模式
> - 采用 **OpenAI 风格的 delta 增量模式**
> - 支持 **消息可见性控制**（用户可见 vs 仅持久化）

#### 3.5.2 事件类型定义

| 事件类型 | 描述 | delta 支持 | 数据结构 |
|----------|------|-----------|----------|
| `message.start` | 消息开始 | - | `{id}` |
| `message.delta` | 消息增量内容 | ✅ | `{id, content, node}` |
| `message.end` | 消息结束 | - | `{id, finish_reason}` |
| `thinking.start` | 思考开始 | - | `{id}` |
| `thinking.delta` | 思考增量内容 | ✅ | `{id, content, node}` |
| `thinking.end` | 思考结束 | - | `{id}` |
| `tool.start` | 工具调用开始 | - | `{id, tool_name, arguments}` |
| `tool.progress` | 工具执行进度 | - | `{id, status, progress}` |
| `tool.end` | 工具调用结束 | - | `{id, status, result_summary}` |
| `board.action` | 看板操作指令 | - | `{action, target, data}` |
| `progress` | 整体进度更新 | - | `{stage, current, total}` |
| `error` | 错误信息 | - | `{error, code, recoverable}` |
| `done` | 流结束 | - | `{}` |

#### 3.5.3 消息可见性控制

```python
# 节点可见性配置
NODE_VISIBILITY = {
    # 对话调度层 - 用户可见
    "entry": "user",
    "intent_detection": "user",
    "status_query": "user",
    "clarify": "user",
    "response_formatter": "user",
    
    # 业务执行层 - 仅持久化，不发 SSE
    "production_manager": "internal",
    "asset_generation": "internal",
    "storyboard_creation": "internal",
    "audio_processing": "internal",
    "video_generation": "internal",
    "editing": "internal",
    "director": "internal",
}

# visibility 值说明
# "user": 发送 SSE + 持久化
# "internal": 仅持久化，不发 SSE
```

#### 3.5.4 SSE 消息结构

```python
# SSE 事件格式
event: {event_type}
data: {json_payload}

# 完整消息结构
{
    "id": "msg_xxx",           # 消息/事件 ID
    "content": "让我帮你...",   # 内容（delta 时为增量）
    "node": "intent_detection", # 来源节点
    "layer": "dispatch",        # 层次: dispatch | execution
    "visibility": "user",       # 可见性: user | internal
    "timestamp": 1706540000     # 时间戳
}
```

#### 3.5.5 LangGraph 到 SSE 的转换

```python
async def langgraph_to_sse(
    graph,
    input_state: dict,
    is_streaming: bool = True
) -> AsyncIterator[str]:
    """将 LangGraph 输出转换为 SSE 事件流"""
    
    message_id = generate_id()
    
    # 发送消息开始
    if is_streaming:
        yield format_sse("message.start", {"id": message_id})
    
    # 流式处理 LangGraph 输出
    async for chunk, metadata in graph.astream(
        input_state, 
        stream_mode="messages"
    ):
        node = metadata.get("langgraph_node")
        visibility = NODE_VISIBILITY.get(node, "internal")
        layer = "dispatch" if node in DISPATCH_NODES else "execution"
        
        # 1. 持久化（所有消息都写入）
        await persist_message(
            message_id=message_id,
            content=chunk.content,
            node=node,
            visibility=visibility,
            metadata=metadata
        )
        
        # 2. SSE 发送（只发送用户可见的）
        if is_streaming and visibility == "user" and chunk.content:
            event_type = get_event_type(node, metadata)
            yield format_sse(event_type, {
                "id": message_id,
                "content": chunk.content,
                "node": node,
                "layer": layer
            })
        
        # 3. 处理工具调用
        if chunk.tool_call_chunks:
            for tool_chunk in chunk.tool_call_chunks:
                yield format_sse("tool.progress", {
                    "id": tool_chunk.get("id"),
                    "tool_name": tool_chunk.get("name"),
                    "status": "running"
                })
    
    # 发送消息结束
    if is_streaming:
        yield format_sse("message.end", {
            "id": message_id,
            "finish_reason": "stop"
        })
    
    yield format_sse("done", {})


def get_event_type(node: str, metadata: dict) -> str:
    """根据节点和元数据确定事件类型"""
    tags = metadata.get("tags", [])
    
    # 如果是思考类节点
    if "thinking" in tags or node in ["intent_detection", "router"]:
        return "thinking.delta"
    
    # 默认是消息类
    return "message.delta"


def format_sse(event: str, data: dict) -> str:
    """格式化为 SSE 字符串"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

#### 3.5.6 事件示例

**消息流（用户可见）：**
```
event: message.start
data: {"id": "msg_001"}

event: thinking.delta
data: {"id": "msg_001", "content": "分析用户意图...", "node": "intent_detection"}

event: thinking.delta
data: {"id": "msg_001", "content": "用户想查询角色状态", "node": "intent_detection"}

event: message.delta
data: {"id": "msg_001", "content": "好的", "node": "status_query"}

event: message.delta
data: {"id": "msg_001", "content": "，目前您的", "node": "status_query"}

event: message.delta
data: {"id": "msg_001", "content": "角色「小明」", "node": "status_query"}

event: message.delta
data: {"id": "msg_001", "content": "图片已生成完成。", "node": "status_query"}

event: board.action
data: {"action": "switchView", "target": "characters"}

event: message.end
data: {"id": "msg_001", "finish_reason": "stop"}

event: done
data: {}
```

**工具调用事件：**
```
event: tool.start
data: {"id": "tool_001", "tool_name": "generate_character_image", "arguments": {"character_id": "chr_001"}}

event: tool.progress
data: {"id": "tool_001", "status": "running", "progress": {"current": 1, "total": 3}}

event: tool.end
data: {"id": "tool_001", "status": "success", "result_summary": "角色图片生成完成"}
```

**Board Action 事件：**
```
event: board.action
data: {"action": "switchView", "target": "storyboard"}

event: board.action
data: {"action": "highlight", "target": "scene_3_shot_2", "data": {"duration": 3000}}

event: board.action
data: {"action": "scroll", "target": "video_timeline", "data": {"position": "00:01:23"}}
```

#### 3.5.7 前端处理示例

```typescript
// 前端 SSE 处理
const eventSource = new EventSource(`/api/v1/agent/${creationUuid}/chat`);

let currentMessage = "";

eventSource.addEventListener("message.start", (e) => {
    const data = JSON.parse(e.data);
    console.log("消息开始:", data.id);
});

eventSource.addEventListener("message.delta", (e) => {
    const data = JSON.parse(e.data);
    currentMessage += data.content;  // 累加增量内容
    updateUI(currentMessage);         // 更新 UI
});

eventSource.addEventListener("thinking.delta", (e) => {
    const data = JSON.parse(e.data);
    updateThinkingUI(data.content);   // 显示思考过程
});

eventSource.addEventListener("tool.start", (e) => {
    const data = JSON.parse(e.data);
    showToolIndicator(data.tool_name); // 显示工具调用指示器
});

eventSource.addEventListener("board.action", (e) => {
    const data = JSON.parse(e.data);
    handleBoardAction(data);           // 处理看板操作
});

eventSource.addEventListener("done", () => {
    eventSource.close();
});
```

---

### 3.6 持久化职责划分

#### 3.6.1 职责划分

| 持久化内容 | 负责方 | 存储位置 | 说明 |
|-----------|--------|----------|------|
| **Agent 思考 / 对话** | Agent | `agent_messages` 表 | 对话记录、思考过程 |
| **Graph 检查点** | LangGraph | `checkpoints` 表 | 断点恢复、状态快照 |
| **业务数据** | Tool | 各业务表 | 图片、视频、提示词等 |
| **Tool 调用记录** | Tool / Agent | `agent_messages` + 日志 | 分层记录 |

#### 3.6.2 Tool 调用记录

Tool 调用需要分层记录：

**用户可见层** - 记录到 `agent_messages`：

```python
# message_type = "tool_call"
{
    "role": "assistant",
    "message_type": "tool_call",
    "content": "正在为角色「小明」生成图片...",
    "extra_data": {
        "tool_name": "generate_character_image",
        "tool_status": "running",  # running / success / failed
        "tool_result_summary": "生成成功，已保存到角色资产"
    }
}
```

**系统监控层** - 记录到独立日志表（可选）：

```python
# 用于运维监控和问题排查
class ToolCallLog(Base):
    __tablename__ = "tool_call_logs"
    
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("agent_sessions.session_id"))
    tool_name = Column(String(100))
    input_params = Column(JSONB)      # 调用参数
    output_result = Column(JSONB)     # 返回结果
    status = Column(String(20))       # success / failed / timeout
    duration_ms = Column(Integer)     # 耗时
    error_message = Column(Text)      # 错误信息
    created_at = Column(DateTime)
```

#### 3.6.3 记录的好处

| 好处 | 说明 |
|------|------|
| **用户体验** | 用户能看到 Agent 在做什么 |
| **调试排查** | 出问题时能追踪完整调用链 |
| **成本统计** | 统计生成调用次数和消耗 |
| **审计合规** | 记录操作历史 |

---

### 3.7 Agent 实例管理

#### 3.7.1 设计决策：Workflow 完成即释放 + Checkpoint 恢复

> ⚠️ **核心原则**：
> - Agent 实例在 **Workflow 自然结束后释放**（自动保存 Checkpoint）
> - 到达 **中断点**（如 Human Review）时，保存 Checkpoint 后释放
> - 新消息到达时，若实例不存在，则从 Checkpoint **恢复**
>
> **注：不是"强制销毁"，而是 Workflow 走完后自然结束，实例被 GC 回收。**

```
┌─────────────────────────────────────────────────────────────────┐
│                     Agent 实例生命周期                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   用户消息1                                                     │
│       │                                                         │
│       ▼                                                         │
│   ┌───────────────────────────────────────────────────────┐    │
│   │  创建 Agent 实例                                       │    │
│   │       │                                               │    │
│   │       ├── 执行 Graph Workflow                          │    │
│   │       │                                               │    │
│   │       ├── Workflow 到达中断点（Human Review 等）        │    │
│   │       │       │                                       │    │
│   │       │       └── 自动保存 Checkpoint → 流程结束       │    │
│   │       │                                               │    │
│   └───────────────────────────────────────────────────────┘    │
│                           │                                     │
│                (实例自然释放，等待用户后续输入)                   │
│                           │                                     │
│   用户消息2 ──────────────┘                                     │
│       │                                                         │
│       ▼                                                         │
│   ┌───────────────────────────────────────────────────────┐    │
│   │  实例不存在 → 从 Checkpoint 恢复                        │    │
│   │       │                                               │    │
│   │       ├── 继续 Graph Workflow                          │    │
│   │       │                                               │    │
│   │       ├── Workflow 完成 / 到达下一个中断点              │    │
│   │       │       │                                       │    │
│   │       │       └── 自动保存 Checkpoint → 流程结束       │    │
│   │       │                                               │    │
│   └───────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 3.7.2 Workflow 结束条件（自然释放点）

| 结束条件 | 说明 |
|----------|------|
| **到达 Human Review 节点** | 等待用户确认，流程暂停 |
| **任务执行完成** | 无后续节点，流程正常结束 |
| **发生不可恢复错误** | 记录错误，流程异常结束 |
| **SSE 流结束且无后续任务** | 本轮对话完成 |

#### 3.7.3 实例管理器

```python
# app/agent/manager.py
class AgentInstanceManager:
    """Agent 实例管理器"""
    
    _instances: Dict[str, ComicDramaAgent] = {}  # session_uuid -> Agent
    _locks: Dict[str, asyncio.Lock] = {}         # session_uuid -> Lock
    
    @classmethod
    async def get_or_restore(cls, session_uuid: str, checkpointer, **kwargs) -> ComicDramaAgent:
        """获取现有实例，或从 Checkpoint 恢复"""
        # 1. 检查是否有现有实例
        if session_uuid in cls._instances:
            return cls._instances[session_uuid]
        
        # 2. 无现有实例，尝试从 Checkpoint 恢复
        agent = ComicDramaAgent(session_uuid, **kwargs)
        checkpoint = await checkpointer.get(session_uuid)
        if checkpoint:
            await agent.restore_from_checkpoint(checkpoint)
        
        cls._instances[session_uuid] = agent
        cls._locks[session_uuid] = asyncio.Lock()
        return agent
    
    @classmethod
    async def run_and_cleanup(cls, session_uuid: str, message: str, **kwargs) -> AsyncIterator:
        """执行消息处理，任务完成后自动销毁"""
        agent = await cls.get_or_restore(session_uuid, **kwargs)
        
        # 获取锁，确保消息顺序处理
        async with cls._locks[session_uuid]:
            try:
                async for event in agent.process_message(message):
                    yield event
                    
                    # 检查是否到达销毁点
                    if event.get("type") == "checkpoint_and_destroy":
                        break
            finally:
                # 任务完成，保存 Checkpoint 并销毁
                if agent.should_destroy:
                    await agent.save_checkpoint()  # 原子事务
                    await cls._destroy(session_uuid)
    
    @classmethod
    async def _destroy(cls, session_uuid: str):
        """销毁实例"""
        if session_uuid in cls._instances:
            del cls._instances[session_uuid]
        if session_uuid in cls._locks:
            del cls._locks[session_uuid]
```

#### 3.7.4 消息处理流程

```
用户消息
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. AgentInstanceManager.get_or_restore(session_uuid)           │
│     - 现有实例存在？直接返回                                     │
│     - 不存在？从 Checkpoint 恢复 / 创建新实例                    │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. 获取 Session 锁（保证单实例）                                │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. Agent.process_message(message)                              │
│     - 消息加入状态                                               │
│     - 执行 Graph 工作流                                         │
│     - 流式返回事件                                               │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. 到达销毁点？                                                 │
│     - Human Review 节点                                         │
│     - 任务完成                                                   │
│     - 不可恢复错误                                               │
└─────────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. 保存 Checkpoint（事务）→ 销毁实例 → 释放锁                  │
```

#### 3.7.5 API 层实现

```python
@router.post("/{creation_uuid}/agent/chat")
async def agent_chat(creation_uuid: str, request: ChatRequest, ...):
    """纯 SSE 处理，零业务逻辑"""
    
    async def event_generator():
        session = await get_or_create_session(db, creation_uuid, user_id)
        
        # 通过管理器执行消息（自动恢复/销毁）
        async for event in AgentInstanceManager.run_and_cleanup(
            session_uuid=session.uuid,
            message=request.message,
            checkpointer=checkpointer,
            db_session=db
        ):
            yield format_sse_event(event)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

#### 3.7.6 状态同步机制

| 场景 | 行为 |
|------|------|
| 首次消息 | 创建新实例 |
| 任务完成 / Human Review | Checkpoint → 销毁 |
| 新消息到达（实例不存在） | 从 Checkpoint 恢复 |
| 服务重启 | 从 Checkpoint 恢复 |

#### 3.7.7 持久化时机

| 事件 | 持久化动作 |
|------|-----------|
| 用户消息到达 | 写入 `agent_messages` |
| 节点执行完成 | Checkpointer 自动保存 |
| Tool 调用完成 | 写入 `agent_messages` + 业务表 |
| 实例空闲超时 | 最终 Checkpoint |
| 服务重启前 | 强制 Checkpoint |

---

## 4. 文件变更清单

### 4.1 新增文件

| 文件路径 | 说明 |
|----------|------|
| `app/agent/prompts/__init__.py` | 提示词模块 |
| `app/agent/prompts/loader.py` | 提示词加载器 |
| `app/agent/prompts/intent_detection.md` | 意图识别提示词 |
| `app/agent/prompts/status_response.md` | 状态回复提示词 |
| `app/agent/prompts/clarify_response.md` | 引导回复提示词 |
| `app/agent/prompts/task_confirmation.md` | 任务确认提示词 |
| `app/agent/graph/nodes/__init__.py` | 节点模块 |
| `app/agent/graph/nodes/intent_detection.py` | 意图识别节点 |
| `app/agent/graph/nodes/router.py` | 路由节点 |
| `app/agent/graph/nodes/status_query.py` | 状态查询节点 |
| `app/agent/graph/nodes/task_execution.py` | 任务执行节点 |
| `app/agent/graph/nodes/clarify.py` | 引导澄清节点 |
| `app/agent/graph/nodes/human_review.py` | 人工确认节点 |
| `app/agent/graph/nodes/response_formatter.py` | 响应格式化节点 |
| `app/agent/tools/db_tools.py` | 数据库工具 |
| `app/agent/handlers/sse_formatter.py` | SSE 格式化 |
| `app/agent/state/persistence.py` | 状态持久化 |
| `app/agent/state/messages.py` | 消息历史管理 |

### 4.2 修改文件

| 文件路径 | 变更内容 |
|----------|----------|
| `app/agent/graph/comic_drama_graph.py` | 重构节点和边定义，接入新节点 |
| `app/api/api_v1/endpoints/agent.py` | 简化为 Graph 入口 |
| `app/agent/tools/generation_tools.py` | 拆分为多个独立 Tool |

### 4.3 标记废弃

| 文件路径 | 说明 |
|----------|------|
| `app/agent/handlers/task_handler.py` | 功能迁移到 Graph 节点后标记 deprecated |
| `app/agent/handlers/status_query_handler.py` | 功能迁移到 Graph 节点后标记 deprecated |

---

## 5. 实施步骤

### Phase 1: 基础架构 (预计 2 天)

**1.1 提示词模块**
- 创建 `app/agent/prompts/` 目录
- 实现 `loader.py` 提示词加载器
- 创建核心提示词文件

**1.2 Graph 节点结构**
- 创建 `app/agent/graph/nodes/` 目录
- 实现 `intent_detection` 节点
- 实现 `router` 节点

### Phase 2: Tools 实现 (预计 3 天)

**2.1 DB Tools**
- 实现 `query_*` 系列工具
- 实现 `update_*` 系列工具

**2.2 生成类 Tools**
- 重构现有生成函数为 Tool 格式
- 保持与 Celery 的兼容

### Phase 3: 节点实现 (预计 3 天)

**3.1 核心节点**
- `status_query.py`
- `task_execution.py`
- `clarify.py`
- `human_review.py`
- `response_formatter.py`

**3.2 状态管理**
- `persistence.py` 状态持久化
- `messages.py` 消息历史管理

### Phase 4: 集成与测试 (预计 2 天)

**4.1 API 重构**
- 简化 Chat API
- 移除意图分发逻辑
- 接入 Graph 工作流

**4.2 SSE 格式化**
- 实现 Graph 输出到 SSE 转换

**4.3 测试**
- 端到端测试

---

## 6. 验证计划

### 6.1 单元测试

```bash
# 提示词加载
pytest tests/agent/test_prompt_loader.py -v

# Tool 功能
pytest tests/agent/test_tools.py -v

# 节点逻辑
pytest tests/agent/test_nodes.py -v
```

### 6.2 集成测试

```bash
# Graph 工作流
pytest tests/agent/test_graph_integration.py -v

# SSE 输出
pytest tests/agent/test_sse_output.py -v
```

### 6.3 手动测试场景

| 场景 | 输入 | 预期行为 |
|------|------|----------|
| 基础对话 | "帮我分析剧本的角色" | 触发 analyze_character |
| 状态查询 | "当前进度如何" | 触发 status_query |
| 未知意图 | "你好" | 触发 clarify |
| 任务执行 | "生成角色图片" | 调用 generate_character_image Tool |

---

## 7. 已确认决策

> ✅ **以下问题已经确认**

### 7.1 Celery 任务保留

- **决策**: 保留 Celery，通过 Tool 封装 Celery 任务
- **说明**: 生成类 Tool 内部调用 Celery 任务，并返回 task_id 给 Graph 状态

### 7.2 Human Review 触发条件

- **决策**: 在以下节点触发 Human Review：
  1. **资产生成后** - 角色/场景图片生成完成后
  2. **分镜拆分后** - 分镜分析完成后
  3. **分镜图/视频生成前** - 开始生成分镜图片或视频前

### 7.3 错误重试策略

- **决策**: 自动重试 3 次，失败后触发 Human Review
- **实现**:
  ```python
  # 在 Tool 内部实现重试逻辑
  for attempt in range(3):
      try:
          result = await execute_task()
          return result
      except Exception as e:
          if attempt == 2:  # 最后一次尝试
              return {"status": "failed", "need_human_review": True, "error": str(e)}
          await asyncio.sleep(1)  # 等待1秒后重试
  ```

### 7.4 并行生成控制

- **决策**: 不在 Graph/Tool 层控制并发
- **说明**: 生成任务通过 Tool 交给 Celery，并发控制由 Celery Worker 配置完成

---

## 附录

### A. 相关文档

- [漫剧Agent产品设计文档.md](./漫剧Agent产品设计文档.md)
- [app/agent/README.md](./app/agent/README.md)

### B. 术语表

| 术语 | 解释 |
|------|------|
| Graph | LangGraph 工作流图 |
| Node | 工作流中的节点，处理特定逻辑 |
| Tool | Agent 可调用的工具函数 |
| SSE | Server-Sent Events，服务端推送 |
| Celery | 异步任务队列 |

---

> **文档维护**: 技术团队  
> **最后更新**: 2026-01-29  
> **版本历史**:
> - v1.1 (2026-01-29): 确认设计决策，更新架构图
> - v1.0 (2026-01-29): 初稿
