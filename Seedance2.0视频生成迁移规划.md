# 视频生成流程迁移计划

> 从"分镜图片→视频"迁移到"角色图+场景图+视频提示词→视频"的新工作方式

## 当前状态

### 已完成（可直接使用）

| 文件 | 说明 |
|------|------|
| `app/agent/graph/nodes/teams/video_prompt_builder.py` | VideoPromptBuilderNode 节点类（ReAct） |
| `app/agent/tools/video_prompt_builder_tools.py` | `analyze_shot_continuity` + `save_video_prompt_result` 工具 |
| `app/prompt/video_prompt_builder.md` | 系统提示词模板（含专业运镜/构图/灯光/声音维度 + 知识库集成） |
| `app/agent/graph/nodes/teams/__init__.py` | 已添加导出 |
| `app/agent/graph/comic_drama_subgraph.py` | `video_prompt_builder_node()` 包装函数已定义（未注册到图中） |

### 未注册

VideoPromptBuilderNode **未注册到 Supervisor 路由和 Graph 中**。需要在完成下述迁移后统一接入。

---

## 迁移步骤

### Phase 1: 接入 Seedance 2.0 API

**目标**：在 AIClient 中新增 Seedance 2.0 的视频生成方法，支持 @引用语法（角色图/场景图/分镜视频作为参考输入）。

**涉及文件**：
- `app/utils/ai_client.py` — 新增 `generate_video_seedance2()` 方法
  - 支持传入多个参考图片（角色图、场景图）
  - 支持传入参考视频（前序分镜视频，用于视频延长）
  - 支持 extend 模式（视频延长）和 new 模式（新视频生成）
  - 解析 `references` 列表，将 `target_id` 解析为实际的资源 URL 传给 API

**需确认**：
- [ ] Seedance 2.0 API 文档和鉴权方式
- [ ] API 支持的参数格式（参考图片如何传入、视频延长如何触发）
- [ ] 计费模型（用于积分冻结计算）

---

### Phase 2: 开发新的 Celery Task

**目标**：新建一个 Celery Task 专门处理新流程的视频生成，读取 `shot.extra_data` 中的 `video_prompt`、`prompt_params`、`references`，调用 Seedance 2.0 API。

**新建文件**：
- `app/tasks/video_prompt_gen_task.py` — 新的视频生成 Celery Task

**核心逻辑**：
```python
@celery_app.task(name="generate_video_from_prompt")
def generate_video_from_prompt_task(shot_id: int, creation_uuid: str):
    # 1. 从 DB 读取 shot.extra_data
    #    - video_prompt: 提示词文本
    #    - prompt_params: {"generation_mode": "extend"/"new", "duration": 10, ...}
    #    - references: [{"type": "character", "target_id": 24, "name": "xxx"}, ...]
    #
    # 2. 解析 references → 获取实际资源 URL
    #    - type=character → Character.image_url
    #    - type=scene → Scene.image_url
    #    - type=shot → Shot.video_url（前序分镜的已生成视频）
    #
    # 3. 根据 generation_mode 调用 Seedance 2.0 API
    #    - extend → 传入前序视频 + 参考角色图/场景图 + 提示词
    #    - new → 传入参考角色图/场景图 + 提示词
    #
    # 4. 轮询等待生成完成
    # 5. 下载视频 → 分离音视频 → 上传 US3
    # 6. 更新 shot 记录（video_url, audio_url, video_status）
    # 7. 积分确认
```

**批量版本**：
- `generate_all_videos_from_prompt_task(creation_uuid)` — 为所有有 `video_prompt` 的分镜批量派发任务

---

### Phase 3: 替换 shot_generation 节点

**目标**：在 Graph 中用 `video_prompt_builder` 替换 `shot_generation`（分镜图片生成），不再生成首尾帧图片。

**修改文件**：

1. **`app/agent/graph/comic_drama_subgraph.py`**
   - 将已定义的 `video_prompt_builder_node` 注册到图中
   - 替换 `shot_generation` 在 Supervisor 路由中的位置
   - 新流程：`storyboard_creation → video_prompt_builder → video_generation → editing`

2. **`app/agent/graph/nodes/teams/supervisor.py`**
   - `worker_node_map` 中添加 `"video_prompt_builder": "video_prompt_builder"`
   - 更新 Supervisor 系统提示词：
     - 分镜创建完成后 → 调度 `video_prompt_builder`（不再调度 `shot_generator`）
     - `video_prompt_builder` 完成后 → 调度 `video_editor`
   - 移除 `shot_generator` 的相关调度逻辑

3. **`app/agent/graph/nodes/teams/video_editor.py`**（或新建替代节点）
   - 修改视频生成节点，改为调用 Phase 2 中的新 Celery Task
   - 不再从 `shot.image_url` 读取首帧图片
   - 改为从 `shot.extra_data["references"]` 读取资源引用

**可删除的文件/代码**：
- `shot_generation_node()` 函数（comic_drama_subgraph.py）
- `ShotGenerationWorkerNode` 类（如果完全不再使用）
- `shot_generation` 相关的图注册和边

---

### Phase 4: 重写 Asset Regenerator

**目标**：`AssetRegeneratorWorkerNode` 不再支持重新生成分镜图片/图片提示词，改为支持重新生成**视频提示词**和**重新生成视频**。

**修改文件**：
- `app/agent/graph/nodes/teams/asset_regenerator_worker.py`

**需要删除的能力**：
- ❌ 重新生成分镜首帧/尾帧图片
- ❌ 重新生成分镜图片提示词
- ❌ `submit_shot_image_regeneration` 工具引用

**需要新增的能力**：
- ✅ 重新生成分镜视频提示词（调用 VideoPromptBuilderNode 的逻辑，为指定分镜重新构建带@引用的提示词）
- ✅ 重新生成分镜视频（调用 Phase 2 的新 Celery Task）

**工具变更**：
- 移除：`submit_shot_image_regeneration`、`save_shot_image_prompt`、`get_shot_image_prompt_template`
- 新增/替换：
  - `regenerate_shot_video_prompt(shot_id)` — 重新为指定分镜构建视频提示词（使用 video_prompt_builder_tools）
  - `regenerate_shot_video(shot_id, creation_uuid)` — 调用新 Celery Task 重新生成视频
- 保留：角色图片/场景图片相关的重新生成能力不变

---

## 流程对比

### Agent 自动流程

#### 旧流程
```
剧本分析 → 角色/场景生成 → 分镜拆分 → 分镜图片生成（首尾帧）→ 视频提示词 → 视频生成 → 剪辑
                                         ↑ shot_generation          ↑ video_editor
```

#### 新流程
```
剧本分析 → 角色/场景生成 → 分镜拆分 → 视频提示词构建（@引用）→ 视频生成（Seedance 2.0）→ 剪辑
                                       ↑ video_prompt_builder      ↑ 新 Celery Task
```

### 手动生成流程（前端触发）

#### 旧流程（手动）
用户在前端逐个分镜操作：
```
1. 选择分镜 → 生成首帧图片 → 生成尾帧图片
2. 首尾帧图片就绪后 → 点击"生成视频" → 调用旧 Celery Task（首帧图+提示词→视频）
```
前置条件：必须先有首尾帧图片才能生成视频。

#### 新流程（手动）
用户在前端直接对分镜生成视频，不再需要首尾帧图片：
```
1. 选择分镜 → 点击"生成视频"
2. 后端自动执行：
   a. LLM 分析当前分镜关联的角色和场景（类似 Agent 中 VideoPromptBuilderNode 的逻辑）
   b. LLM 分析与前一个分镜的连续性，决定 extend/new 模式
   c. 自动生成带 @引用的视频提示词
   d. 保存提示词和 references 到 shot.extra_data
   e. 调用新 Celery Task 生成视频
```

**前端约束**：
- 如果用户选择了"参考视频生成"模式（即 extend 模式，引用前一个分镜视频延长）：
  - **前一个分镜的视频必须已生成成功**（`video_status == "completed"` 且 `video_url` 存在）
  - 前端需校验此条件，未满足时禁用 extend 模式或提示用户先生成前序分镜视频
  - 后端 API 也需做二次校验，防止引用不存在的视频
- 如果用户选择"新视频"模式（new），则无前置条件，直接生成

**手动生成涉及的接口改造**：

1. **新建 API 接口**：`POST /api/v1/shots/{shot_id}/generate-video`
   - 参数：`{ "mode": "auto" | "extend" | "new" }`
     - `auto`：后端自动判断 extend/new（默认）
     - `extend`：强制使用视频延长模式
     - `new`：强制使用新视频模式
   - 逻辑：
     1. 校验前置条件（extend 模式下前序视频必须存在）
     2. 调用 LLM 为该分镜生成视频提示词（复用 `video_prompt_builder_tools` 中的逻辑）
     3. 保存提示词到 `shot.extra_data`
     4. 派发新 Celery Task 生成视频
     5. 返回 task_id 供前端轮询

2. **新建 API 接口**：`POST /api/v1/shots/{shot_id}/regenerate-video-prompt`
   - 手动重新生成视频提示词（不生成视频）
   - 用户可在前端查看/编辑提示词后再手动触发视频生成

3. **旧接口兼容**：
   - 旧的 `POST /api/v1/shots/{shot_id}/generate-image` 等首尾帧接口暂保留但标记废弃
   - 前端切换到新流程后可移除

### 关键差异
| | 旧流程 | 新流程 |
|---|---|---|
| 分镜图片 | 需要生成首尾帧图片 | **不需要** |
| 视频输入 | 首帧图片 + 视频提示词 | 角色图 + 场景图 + @引用提示词 |
| 视频延长 | 不支持 | 支持（通过 @分镜N 引用前序视频） |
| 视频 API | Wan-AI/Vidu/Doubao/Sora2 | Seedance 2.0 |
| 重新生成 | 重新生成分镜图片+视频 | 重新生成视频提示词+视频 |

---

## 执行顺序建议

```
Phase 1（API 接入）→ Phase 2（Celery Task）→ Phase 3（Graph 替换）→ Phase 4（Regenerator 重写）
```

Phase 1 和 Phase 2 可以在拿到 Seedance 2.0 API 文档后立即开始。
Phase 3 和 Phase 4 依赖 Phase 2 完成。
