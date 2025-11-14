# Celery 任务系统设计文档

## 概述

本系统使用 Celery 作为异步任务队列，管理所有耗时操作，包括：
- 小说上传处理
- AI 生成任务（角色图片、场景描述、分镜图、音频、视频合成等）

## 架构设计

### 1. 任务类型分类

系统定义了统一的任务类型枚举（`TaskType`），支持以下任务类型：

#### 小说相关任务
- `NOVEL_UPLOAD`: 小说上传处理

#### AI 生成任务
- `CHARACTER_IMAGE_GENERATION`: 角色图片生成
- `SCENE_DESCRIPTION_GENERATION`: 场景描述生成
- `SHOT_IMAGE_GENERATION`: 分镜图片生成
- `AUDIO_GENERATION`: 音频生成
- `VIDEO_SYNTHESIS`: 视频合成

#### 批量任务
- `BATCH_CHARACTER_IMAGE_GENERATION`: 批量角色图片生成
- `BATCH_SHOT_IMAGE_GENERATION`: 批量分镜图片生成

### 2. 任务查询接口设计

#### 通用任务查询接口

**端点**: `GET /api/v1/tasks/{task_id}`

**功能**: 查询任意类型任务的状态和进度

**响应格式**:
```json
{
  "task_id": "uuid-string",
  "task_type": "novel_upload",  // 任务类型
  "status": "PROGRESS",  // Celery 任务状态
  "message": "正在处理第 5/20 章",
  "progress": {
    "current": 5,
    "total": 20,
    "percent": 25,
    "status": "正在处理第 5/20 章",
    "stage": "uploading_chapters",
    "success_count": 5,
    "error_count": 0
  },
  "resource": {  // 任务完成后的关联资源（根据任务类型不同）
    "type": "novel",
    "novel_id": 123,
    "novel": {
      "novel_id": 123,
      "title": "小说标题",
      "author": "作者",
      "status": "completed",
      "chapter_count": 20
    }
  }
}
```

**任务状态说明**:
- `PENDING`: 任务等待执行
- `STARTED`: 任务已开始执行
- `PROGRESS`: 任务执行中，有进度信息
- `SUCCESS`: 任务成功完成
- `FAILURE`: 任务失败
- `RETRY`: 任务正在重试
- `REVOKED`: 任务已被撤销

**资源类型**:
根据任务类型，`resource` 字段会包含不同的资源信息：
- `novel_upload` → `{"type": "novel", "novel_id": ..., "novel": {...}}`
- `character_image_generation` → `{"type": "character", "character_id": ..., "character": {...}}`
- `shot_image_generation` → `{"type": "shot", "shot_id": ..., "shot": {...}}`
- `video_synthesis` → `{"type": "creation", "creation_id": ..., "creation": {...}}`

#### 向后兼容接口

**端点**: `GET /api/v1/tasks/{task_id}/novel`

**功能**: 专门用于查询小说上传任务（向后兼容）

**注意**: 此接口仅适用于小说上传任务，其他任务类型请使用通用接口。

### 3. 任务实现规范

#### 3.1 任务函数定义

所有 Celery 任务应遵循以下规范：

```python
@celery_app.task(bind=True, name="task_name")
def task_function(self, ...):
    """
    任务函数必须：
    1. 使用 bind=True 以访问 self
    2. 使用 self.update_state() 更新进度
    3. 返回统一格式的结果字典
    """
    # 更新进度
    self.update_state(
        state='PROGRESS',
        meta={
            'current': 0,
            'total': 100,
            'percent': 0,
            'status': '任务描述',
            'stage': 'processing',
        }
    )
    
    # 任务处理逻辑...
    
    # 返回结果
    return {
        "success": True,
        "resource_id": ...,  # 根据任务类型返回对应的资源ID
        "message": "任务完成"
    }
```

#### 3.2 任务结果格式

所有任务完成时应返回统一格式的结果字典：

**小说上传任务**:
```python
{
    "success": True,
    "novel_id": 123,
    "title": "小说标题",
    "chapter_count": 20,
    "message": "小说处理完成"
}
```

**角色图片生成任务**:
```python
{
    "success": True,
    "character_id": 456,
    "image_url": "https://...",
    "message": "角色图片生成完成"
}
```

**分镜图片生成任务**:
```python
{
    "success": True,
    "shot_id": 789,
    "image_url": "https://...",
    "message": "分镜图片生成完成"
}
```

**视频合成任务**:
```python
{
    "success": True,
    "creation_id": 101,
    "video_url": "https://...",
    "audio_url": "https://...",
    "message": "视频合成完成"
}
```

#### 3.3 进度更新规范

任务应使用 `self.update_state()` 更新进度，格式如下：

```python
self.update_state(
    state='PROGRESS',
    meta={
        'current': 当前进度,
        'total': 总进度,
        'percent': 百分比,
        'status': '状态描述',
        'stage': '处理阶段',
        'success_count': 成功数量（可选）,
        'error_count': 失败数量（可选）,
    }
)
```

**处理阶段（stage）**:
- `initializing`: 初始化
- `processing`: 处理中
- `generating`: 生成中（AI任务）
- `uploading_result`: 上传结果中
- `completing`: 完成中
- `completed`: 已完成
- `failed`: 失败

### 4. 任务类型推断

系统通过任务名称自动推断任务类型（`get_task_type_from_name`），规则如下：
- 包含 `novel_upload` 或 `novel` → `NOVEL_UPLOAD`
- 包含 `character_image` → `CHARACTER_IMAGE_GENERATION`
- 包含 `scene_description` → `SCENE_DESCRIPTION_GENERATION`
- 包含 `shot_image` → `SHOT_IMAGE_GENERATION`
- 包含 `audio` → `AUDIO_GENERATION`
- 包含 `video` 或 `synthesis` → `VIDEO_SYNTHESIS`

### 5. 使用建议

#### 5.1 何时使用 Celery

**推荐使用 Celery 的场景**:
- ✅ 文件上传和处理（如小说上传）
- ✅ AI 生成任务（图片、音频、视频生成）
- ✅ 批量处理任务
- ✅ 耗时操作（超过 5 秒）
- ✅ 需要进度反馈的任务

**不推荐使用 Celery 的场景**:
- ❌ 简单的数据库查询
- ❌ 快速的数据验证
- ❌ 同步的 API 响应

#### 5.2 前端轮询机制

前端应使用以下流程查询任务状态：

```javascript
// 1. 提交任务，获得 task_id
const response = await uploadNovel(file);
const taskId = response.task_id;

// 2. 轮询任务状态
const pollInterval = setInterval(async () => {
  const status = await fetchTaskStatus(taskId);
  
  if (status.status === 'SUCCESS') {
    clearInterval(pollInterval);
    // 处理成功结果
    const resource = status.resource;
    if (resource.type === 'novel') {
      navigate(`/novels/${resource.novel_id}`);
    }
  } else if (status.status === 'FAILURE') {
    clearInterval(pollInterval);
    // 处理失败
    showError(status.error);
  } else if (status.status === 'PROGRESS') {
    // 更新进度条
    updateProgress(status.progress);
  }
}, 2000); // 每2秒轮询一次

// 3. 设置超时（30分钟）
setTimeout(() => {
  clearInterval(pollInterval);
  showError('任务超时');
}, 30 * 60 * 1000);
```

### 6. 扩展新任务类型

添加新任务类型的步骤：

1. **在 `TaskType` 枚举中添加新类型**:
```python
class TaskType(str, Enum):
    NEW_TASK_TYPE = "new_task_type"
```

2. **在 `_get_resource_by_task_result` 中添加资源获取逻辑**:
```python
elif task_type == TaskType.NEW_TASK_TYPE:
    resource_id = result.get("resource_id")
    if resource_id:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if resource:
            return {
                "type": "resource",
                "resource_id": resource_id,
                "resource": {...}
            }
```

3. **在 `get_task_type_from_name` 中添加推断规则**（如需要）:
```python
elif "new_task" in task_name_lower:
    return TaskType.NEW_TASK_TYPE
```

4. **创建任务函数**:
```python
@celery_app.task(bind=True, name="process_new_task")
def process_new_task(self, ...):
    # 实现任务逻辑
    return {
        "success": True,
        "resource_id": ...,
        "message": "任务完成"
    }
```

### 7. 最佳实践

1. **任务命名规范**: 使用清晰的命名，如 `process_novel_upload`、`generate_character_image`
2. **错误处理**: 所有任务都应包含完善的错误处理和日志记录
3. **进度更新**: 对于耗时任务，应定期更新进度（建议每 10% 或每处理一个项目）
4. **资源清理**: 任务完成后应清理临时文件
5. **超时设置**: 根据任务类型设置合理的超时时间
6. **重试机制**: 对于可能失败的任务，配置合理的重试策略

### 8. 配置说明

Celery 配置位于 `app/core/celery_app.py`:

```python
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30分钟超时
    task_soft_time_limit=25 * 60,  # 25分钟软超时
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
```

### 9. 监控和调试

- **查看任务状态**: 使用 `GET /api/v1/tasks/{task_id}` 接口
- **查看 Celery 日志**: 检查 Celery worker 日志输出
- **查看 Redis**: 使用 Redis CLI 查看任务队列和结果
- **Flower**: 可选，使用 Flower 监控 Celery 任务（需要额外安装）

## 总结

通过统一的任务类型系统和通用查询接口，系统可以轻松扩展支持新的任务类型，同时保持 API 的一致性和易用性。所有 AI 生成任务都推荐使用 Celery 进行异步处理，以提供良好的用户体验和系统性能。

