# Agent Workflow 部署文档

## 概述

Agent Workflow 是一个基于 LangGraph 的智能漫画短剧制作工作流系统，能够自动完成从剧本分析到视频生成的完整流程。

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Layer                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              FastAPI Endpoints (agent.py)                │   │
│  │  - POST /sessions           创建会话                      │   │
│  │  - GET  /sessions/{id}/stream  SSE 流式输出              │   │
│  │  - POST /sessions/{id}/feedback  提交反馈                │   │
│  │  - POST /sessions/{id}/resume  恢复工作流                │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Agent Layer                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              ComicDramaGraph (LangGraph)                 │   │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────┐             │   │
│  │  │ Director │───▶│ Script  │───▶│ Asset   │             │   │
│  │  │ Agent   │    │Analysis │    │Generat. │             │   │
│  │  └─────────┘    └─────────┘    └─────────┘             │   │
│  │                      │              │                    │   │
│  │                      ▼              ▼                    │   │
│  │  ┌─────────┐    ┌─────────┐    ┌─────────┐             │   │
│  │  │Editing  │◀───│ Video   │◀───│ Audio   │             │   │
│  │  │Agent   │    │Generat. │    │Process  │             │   │
│  │  └─────────┘    └─────────┘    └─────────┘             │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Tools Layer                                 │
│  ┌──────────────┬──────────────┬──────────────┬─────────────┐  │
│  │ Asset Tools  │Generation    │Review Tools  │Editing      │  │
│  │              │Tools         │              │Tools        │  │
│  │- ReadChar    │- GenCharImg  │- ReviewChar  │- ConcatVid  │  │
│  │- WriteChar   │- GenSceneImg │- ReviewScene │- AddAudio   │  │
│  │- ReadScene   │- GenStoryImg │- BatchReview │- AddSubtitle│  │
│  │- SearchAssets│- GenVideo    │- QualityCheck│- FinalRender│  │
│  └──────────────┴──────────────┴──────────────┴─────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
pip install langgraph>=0.2.0 langchain>=0.3.0 langchain-openai>=0.2.0
pip install chromadb>=0.4.0 tiktoken>=0.5.0
```

### 2. 配置环境变量

```bash
# .env
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL_NAME=gpt-4o
IMAGE_MODEL_TEXT_TO_IMAGE=dall-e-3
LANGGRAPH_CHECKPOINT_NAMESPACE=agent_workflow
CHROMADB_PATH=./chroma_db
```

### 3. 运行数据库迁移

```bash
alembic upgrade head
```

### 4. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API 使用示例

### 创建 Agent 会话

```bash
curl -X POST "http://localhost:8000/api/v1/agent/sessions" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "creation_uuid": "project-uuid",
    "workflow_mode": "AGENT",
    "script_text": "剧本内容..."
  }'
```

### SSE 流式接收进度

```javascript
const response = await fetch(
  'http://localhost:8000/api/v1/agent/sessions/{session_id}/stream',
  { headers: { 'Authorization': 'Bearer {token}' } }
);

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  const lines = chunk.split('\n\n');
  
  for (const line of lines) {
    if (line.startsWith('event: ')) {
      const eventType = line.slice(7);
      const data = line.slice(line.indexOf('data:') + 5);
      console.log(eventType, JSON.parse(data));
    }
  }
}
```

### 提交人工审核

```bash
curl -X POST "http://localhost:8000/api/v1/agent/sessions/{session_id}/feedback" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "feedback_type": "approve",
    "feedback_content": "审核通过"
  }'
```

## 工作流阶段

| 阶段 | 说明 | 人工审核点 |
|------|------|-----------|
| init | 初始化 | 否 |
| script_analysis | 剧本分析 | 否 |
| asset_generation | 资产生成 | 是 |
| storyboard_creation | 分镜创建 | 是 |
| audio_processing | 音频处理 | 否 |
| video_generation | 视频生成 | 否 |
| editing | 剪辑合成 | 否 |
| completed | 完成 | - |

## 状态管理

### 状态结构

```typescript
interface ComicDramaState {
  creation_uuid: string;
  thread_id: string;
  current_stage: ProductionStage;
  script_text: string;
  characters: Character[];
  scenes: Scene[];
  storyboards: Storyboard[];
  audio_segments: AudioSegment[];
  video_segments: VideoSegment[];
  final_video: FinalVideo | null;
  messages: Message[];
  errors: Error[];
  pending_checkpoint: Checkpoint | null;
  metadata: Record<string, any>;
}
```

### 检查点恢复

```python
# 从检查点恢复
await graph.restore_from_checkpoint(
  thread_id="thread-123",
  checkpoint_id="checkpoint-id"
)
```

## 监控和日志

### 日志配置

```python
from app.core.logger import logger

logger.info("工作流开始")
logger.warning("生成失败，尝试重试")
logger.error("严重错误")
```

### LangSmith 集成

```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=your_langsmith_key
export LANGCHAIN_PROJECT=agent-workflow
```

## 故障排查

### 常见问题

1. **ENUM 类型冲突**
   - 运行迁移前确保删除已存在的类型
   - 使用 `CREATE TYPE IF NOT EXISTS`

2. **视频生成超时**
   - 调整超时配置
   - 使用分段生成

3. **API 限流**
   - 实现重试机制
   - 使用熔断器

### 恢复策略

| 错误类型 | 策略 |
|---------|------|
| 网络错误 | 指数退避重试 |
| API 限流 | 等待后重试 |
| 验证错误 | 跳过或使用默认值 |
| 数据库错误 | 回滚到检查点 |

## 性能优化

1. **并发生成**
   - 角色和场景图片并行生成
   - 使用 asyncio.gather

2. **缓存**
   - 缓存重复使用的资产
   - 使用 Redis 缓存 API 响应

3. **流式输出**
   - 使用 SSE 实时推送进度
   - 减少客户端轮询

## 扩展开发

### 添加新的 Agent

1. 在 `agents/` 目录创建新文件
2. 实现节点函数
3. 在 `comic_drama_graph.py` 中注册节点

### 添加新的工具

1. 在 `tools/` 目录创建新文件
2. 继承 `BaseTool` 类
3. 实现 `execute` 方法

### 自定义工作流

```python
graph = ComicDramaGraph(session_factory)
# 修改节点和边
graph.graph.add_node("custom_node", custom_node_func)
graph.graph.add_edge("from_node", "custom_node")
```
