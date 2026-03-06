# 英语单词视频生成功能 - 详细实现方案

## 一、需求澄清

### 1.1 核心需求
- **输入**: 3-5个英语单词
- **输出**: 自动生成的英语单词教学视频
- **视频结构**: 单词展示(5s) → 单词解释(3-5s) → 循环
- **音频**: 由视频生成API通过提示词控制生成（不需要单独的TTS）
- **触发方式**: API 触发 或 聊天触发（都通过 Agent 执行）
- **支持的配置**： 
    - 单词数量和内容（3-5个单词） 
    - 单词念两遍，翻译念一遍（单词/翻译念的次数 默认单词2次 翻译1次）
    - 将单词组成一个句子，句子的内容变为具体的视频内容，带配音句子放在视频的顶部。（是否开启这个功能 开启了之后 分镜就要加这一条分镜。）
### 1.2 特殊说明
- **不需要TTS**: 视频生成API支持生成带音频的视频，只要提示词写好即可
- **Agent通用化**: 将原有漫剧Agent改造为通用创作Agent，支持多种创作类型

---

## 二、现有系统架构分析

### 2.1 现有架构
```
┌─────────────────────────────────────────────┐
│            DialogueGraph (对话调度层)         │
│  entry → intent_detection → task_execution │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│       ComicDramaSubgraph (漫剧执行子图)       │
│  stage_router → supervisor → workers        │
└─────────────────────┬───────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│              GraphRunner (执行器)            │
└─────────────────────────────────────────────┘
```

### 2.2 现有文件结构
```
app/agent/
├── api/chat.py                    # 聊天API
├── graph/
│   ├── dialogue_graph.py           # 对话调度图
│   ├── comic_drama_subgraph.py    # 漫剧执行子图
│   ├── runner.py                  # Graph执行器
│   └── nodes/
│       └── intent_detection.py    # 意图识别
├── prompts/
│   └── intent_detection.md        # 意图识别提示词
├── state/
│   └── schemas.py                 # 状态定义
└── tools/                         # 工具层
```

---

## 三、改造方案

### 3.1 核心思路

**将 ComicDramaSubgraph 改造为通用的 BusinessSubgraph，支持多种创作类型**

```
┌─────────────────────────────────────────────────────────────┐
│                    通用 BusinessSubgraph                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  creation_type: "comic_drama" | "word_video" | ...         │
│                                                              │
│  ┌─────────────────┐    ┌─────────────────┐               │
│  │ ComicDramaWorker │    │ WordVideoWorker │               │
│  └────────┬────────┘    └────────┬────────┘               │
│           │                       │                         │
│           └───────────┬───────────┘                         │
│                       ▼                                      │
│              ┌─────────────┐                                │
│              │ VideoExport  │                                │
│              └─────────────┘                                │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 需要新增/修改的文件

#### A. 新增文件

| 文件路径 | 说明 |
|---------|------|
| `app/agent/workers/word_video_worker.py` | 英语单词视频执行Worker |
| `app/agent/workers/base_worker.py` | 通用Worker基类 |
| `app/agent/prompts/word_video_*.md` | 单词视频相关提示词 |
| `app/api/api_v1/endpoints/word_video.py` | 单词视频API端点 |
| `app/models/word_video.py` | 单词视频数据模型 |

#### B. 修改文件

| 文件路径 | 修改内容 |
|---------|---------|
| `app/agent/graph/dialogue_graph.py` | 改为通用调度 |
| `app/agent/graph/comic_drama_subgraph.py` | 改造为BusinessSubgraph |
| `app/agent/graph/nodes/intent_detection.py` | 支持新意图 |
| `app/agent/prompts/intent_detection.md` | 新增意图类型 |
| `app/agent/state/schemas.py` | 新增创作类型枚举 |
| `app/agent/graph/runner.py` | 支持API触发 |

---

## 四、详细实现步骤

### 4.1 第一步：定义创作类型枚举

**修改文件**: `app/agent/state/schemas.py`

```python
from enum import StrEnum

class CreationType(StrEnum):
    """创作类型枚举"""
    COMIC_DRAMA = "comic_drama"      # 漫剧
    WORD_VIDEO = "word_video"         # 英语单词视频
    # 未来可扩展:
    # STORY_BOOK = "story_book"       # 绘本
    # POEM_VIDEO = "poem_video"       # 诗歌视频

class WordVideoConfig(TypedDict):
    """英语单词视频配置"""
    words: List[str]                        # 单词列表
    word_count: int                        # 单词数量(3-5)
    voice_gender: Literal["female", "male"]
    voice_age: Literal["child", "adult"]
    sentence_level: Literal["kindergarten", "primary", "middle"]
    style: str                             # 风格

class ComicDramaState(TypedDict):
    # ... 现有字段 ...
    
    # 新增字段
    creation_type: Optional[CreationType]  # 创作类型
    word_video_config: Optional[WordVideoConfig]  # 单词视频配置
```

### 4.2 第二步：修改意图识别

**修改文件**: `app/agent/prompts/intent_detection.md`

新增意图类型：

```markdown
### 制作类 (production) - 新增

**英语单词视频类：**
- `create_word_video` - 创建英语单词教学视频
- `configure_word_video` - 配置单词视频参数

### 继续工作流规则 - 修改

| 当前阶段 | 返回意图 | details |
|---------|---------|---------|
| ... | ... | ... |
| WORD_VIDEO_CONFIGURED | `generate_word_video` | `{"description": "开始生成单词视频"}` |
```

**修改文件**: `app/agent/graph/nodes/intent_detection.py`

添加解析逻辑：

```python
def _parse_intent_response(response: str) -> Dict[str, Any]:
    # ... 现有逻辑 ...
    
    # 新增: 英语单词视频
    if "word_video" in intent.lower():
        if "create" in intent.lower():
            return {"intent": "create_word_video", "intent_category": "production", ...}
```

### 4.3 第三步：创建Worker基类

**新增文件**: `app/agent/workers/base_worker.py`

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from app.agent.state.schemas import ComicDramaState

class BaseWorker(ABC):
    """通用Worker基类"""
    
    @property
    @abstractmethod
    def worker_type(self) -> str:
        """Worker类型标识"""
        pass
    
    @abstractmethod
    async def execute(self, state: ComicDramaState) -> Dict[str, Any]:
        """执行工作"""
        pass
    
    async def can_handle(self, state: ComicDramaState) -> bool:
        """判断是否能处理当前状态"""
        return state.get("creation_type") == self.worker_type

class WorkerRegistry:
    """Worker注册中心"""
    
    _workers: Dict[str, BaseWorker] = {}
    
    @classmethod
    def register(cls, worker: BaseWorker):
        cls._workers[worker.worker_type] = worker
    
    @classmethod
    def get(cls, worker_type: str) -> BaseWorker:
        return cls._workers.get(worker_type)
    
    @classmethod
    def get_all(cls) -> List[BaseWorker]:
        return list(cls._workers.values())
```

### 4.4 第四步：实现单词视频Worker

**新增文件**: `app/agent/workers/word_video_worker.py`

```python
from typing import Dict, Any, List
from app.agent.workers.base_worker import BaseWorker, WorkerRegistry
from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.core.logger import logger

class WordVideoWorker(BaseWorker):
    """英语单词视频Worker"""
    
    @property
    def worker_type(self) -> str:
        return "word_video"
    
    async def execute(self, state: ComicDramaState) -> Dict[str, Any]:
        """执行单词视频生成"""
        logger.info("[WordVideoWorker] 开始执行")
        
        config = state.get("word_video_config", {})
        words = config.get("words", [])
        
        # 步骤1: 解析单词，生成展示分镜
        word_display_shots = await self._generate_word_display_shots(words, config)
        
        # 步骤2: 生成解释分镜
        explanation_shots = await self._generate_explanation_shots(words, config)
        
        # 步骤3: 生成视频
        await self._generate_videos(word_display_shots + explanation_shots, config)
        
        # 步骤4: 剪辑导出
        final_video_url = await self._export_video(
            word_display_shots + explanation_shots,
            config
        )
        
        return {
            "final_video_url": final_video_url,
            "current_stage": ProductionStage.COMPLETED,
        }
    
    async def _generate_word_display_shots(
        self, 
        words: List[str], 
        config: Dict
    ) -> List[Dict]:
        """生成单词展示分镜"""
        shots = []
        
        for word in words:
            # 1. 生成视频提示词（多彩背景+单词+翻译）
            prompt = self._build_display_prompt(word, config)
            
            # 2. 保存到数据库
            shot = await self._save_shot({
                "type": "word_display",
                "word": word,
                "video_prompt": prompt,
                "audio_text": f"{word}, {word}, {self._get_translation(word)}",
                "duration": 5,
            })
            shots.append(shot)
        
        return shots
    
    async def _generate_explanation_shots(
        self, 
        words: List[str], 
        config: Dict
    ) -> List[Dict]:
        """生成单词解释分镜"""
        shots = []
        
        sentence_level = config.get("sentence_level", "primary")
        
        for word in words:
            # 1. 生成句子
            sentence = await self._generate_sentence(word, sentence_level)
            
            # 2. 生成视频提示词
            prompt = await self._build_explanation_prompt(sentence, word, config)
            
            # 3. 保存
            shot = await self._save_shot({
                "type": "word_explanation",
                "word": word,
                "sentence": sentence,
                "video_prompt": prompt,
                "audio_text": sentence,
                "duration": 4,
            })
            shots.append(shot)
        
        return shots
    
    def _build_display_prompt(self, word: str, config: Dict) -> str:
        """构建单词展示视频提示词"""
        # 绚烂的多彩背景
        prompt = f"""
Create a vibrant, colorful abstract background with swirling colors blending together.
The background should be colorful gradient, cartoon style, dreamy and brilliant.

Style requirements:
- Multiple colors naturally blending and swirling (red, orange, yellow, green, blue, purple)
- Center of the image displays the white English word: "{word}"
- Word uses bold sans-serif font, modern and clean
- Below the word shows the Chinese translation: "{self._get_translation(word)}"
- Overall style: Childlike, cartoon, colorful, educational

Audio requirement (for video generation):
- Pronounce the word twice, then the translation once
- Example: "apple, apple, 苹果"
- Child-friendly, clear pronunciation
"""
        return prompt
    
    async def _build_explanation_prompt(
        self, 
        sentence: str, 
        word: str, 
        config: Dict
    ) -> str:
        """构建单词解释视频提示词"""
        # 查询相关场景
        scene = await self._select_scene(sentence, config)
        
        prompt = f"""
Generate a {scene} scene in cartoon style.

Scene elements:
- Top of the frame displays the sentence: "{sentence}"
- The sentence uses white font with rounded rectangle background
- Characters naturally demonstrate the sentence meaning
- Bright colors, childlike style
- Educational and warm atmosphere
- Disney/Pixar animation quality

Audio requirement (for video generation):
- Read the sentence: "{sentence}"
- Child-friendly, clear pronunciation
- Natural, conversational tone
"""
        return prompt
    
    # ... 其他辅助方法

# 注册Worker
WorkerRegistry.register(WordVideoWorker())
```

### 4.5 第五步：改造BusinessSubgraph

**修改文件**: `app/agent/graph/comic_drama_subgraph.py`

```python
async def business_router_node(state: ComicDramaState) -> Dict[str, Any]:
    """业务路由节点 - 根据creation_type选择Worker"""
    
    creation_type = state.get("creation_type", "comic_drama")
    
    if creation_type == "word_video":
        return {"next_worker": "word_video_worker"}
    elif creation_type == "comic_drama":
        return {"next_worker": "comic_drama_worker"}
    else:
        raise ValueError(f"Unknown creation_type: {creation_type}")

async def execute_worker_node(state: ComicDramaState) -> Dict[str, Any]:
    """执行Worker节点"""
    
    worker_type = state.get("next_worker", "comic_drama_worker")
    worker = WorkerRegistry.get(worker_type)
    
    if not worker:
        raise ValueError(f"Worker not found: {worker_type}")
    
    return await worker.execute(state)

def build_business_subgraph() -> StateGraph:
    """构建通用业务子图"""
    
    workflow = StateGraph(ComicDramaState)
    
    # 路由节点
    workflow.add_node("business_router", business_router_node)
    
    # Worker执行节点
    workflow.add_node("execute_worker", execute_worker_node)
    
    # 视频导出节点（通用）
    workflow.add_node("video_export", video_export_node)
    
    # 边
    workflow.set_entry_point("business_router")
    workflow.add_edge("business_router", "execute_worker")
    workflow.add_edge("execute_worker", "video_export")
    workflow.add_edge("video_export", END)
    
    return workflow.compile()
```

### 4.6 第六步：新增API端点

**新增文件**: `app/api/api_v1/endpoints/word_video.py`

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Literal

router = APIRouter(prefix="/word-video", tags=["Word Video"])

class CreateWordVideoRequest(BaseModel):
    """创建单词视频请求"""
    words: List[str]                          # 3-5个单词
    voice_gender: Literal["female", "male"] = "female"
    voice_age: Literal["child", "adult"] = "child"
    sentence_level: Literal["kindergarten", "primary", "middle"] = "primary"

class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str                              # processing/completed/failed
    progress: int                             # 0-100
    current_step: str
    video_url: str = None


@router.post("/create")
async def create_word_video(
    request: CreateWordVideoRequest,
    current_user = Depends(get_current_user)
):
    """
    创建英语单词视频生成任务
    
    通过Agent执行，返回任务ID
    """
    # 1. 创建任务记录
    task = await WordVideoTask.create(
        user_id=current_user.id,
        words=request.words,
        voice_gender=request.voice_gender,
        voice_age=request.voice_age,
        sentence_level=request.sentence_level,
    )
    
    # 2. 触发Agent执行
    await trigger_agent_for_word_video(
        user_id=current_user.id,
        task_id=task.task_id,
        config={
            "words": request.words,
            "voice_gender": request.voice_gender,
            "voice_age": request.voice_age,
            "sentence_level": request.sentence_level,
        }
    )
    
    return {
        "task_id": str(task.task_id),
        "status": "processing"
    }


@router.get("/{task_id}/status")
async def get_task_status(
    task_id: str,
    current_user = Depends(get_current_user)
):
    """查询任务状态"""
    task = await WordVideoTask.get_by_task_id(task_id, current_user.id)
    
    return TaskStatusResponse(
        task_id=str(task.task_id),
        status=task.status,
        progress=task.progress,
        current_step=task.current_step,
        video_url=task.video_url,
    )


@router.get("/{task_id}/download")
async def download_video(
    task_id: str,
    current_user = Depends(get_current_user)
):
    """下载视频"""
    task = await WordVideoTask.get_by_task_id(task_id, current_user.id)
    
    if not task.video_url:
        raise HTTPException(status_code=404, detail="视频未生成")
    
    # 返回视频文件或重定向
    return RedirectResponse(task.video_url)
```

### 4.7 第七步：实现API触发逻辑

**新增文件**: `app/agent/triggers/api_trigger.py`

```python
async def trigger_agent_for_word_video(
    user_id: int,
    task_id: str,
    config: Dict
):
    """
    通过API触发Agent执行单词视频生成
    
    复用GraphRunner，但现有的需要特殊处理：
    1. 直接设置creation_type和配置
    2. 不经过意图识别
    3. 直接进入业务执行
    """
    from uuid import uuid4
    from app.agent.graph.runner import GraphRunner
    
    # 创建任务专属的thread_id
    thread_id = f"word_video_{task_id}_{uuid4().hex[:8]}"
    creation_uuid = f"word_video_{task_id}"
    
    # 构建初始状态
    initial_state = {
        "creation_uuid": creation_uuid,
        "thread_id": thread_id,
        "user_id": user_id,
        "creation_type": "word_video",
        "word_video_config": config,
        "task_id": task_id,  # 用于后续更新进度
        "current_stage": "WORD_VIDEO_INIT",
    }
    
    # 执行Graph
    runner = GraphRunner(
        creation_uuid=creation_uuid,
        thread_id=thread_id,
        user_id=user_id,
    )
    
    # 直接执行，不需要流式输出
    await runner.execute_word_video(initial_state)
```

**修改文件**: `app/agent/graph/runner.py`

```python
class GraphRunner:
    # ... 现有代码 ...
    
    async def execute_word_video(self, initial_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单词视频生成（API触发）
        
        直接进入业务执行，不经过意图识别
        """
        from app.agent.graph.comic_drama_subgraph import build_business_subgraph
        
        # 构建业务子图
        business_graph = build_business_subgraph()
        
        # 配置
        config = {"configurable": {"thread_id": self.thread_id}}
        
        # 执行
        result = await business_graph.ainvoke(initial_state, config)
        
        # 更新任务状态
        await self._update_word_video_task(result)
        
        return result
    
    async def _update_word_video_task(self, result: Dict[str, Any]):
        """更新单词视频任务状态"""
        task_id = result.get("task_id")
        if not task_id:
            return
        
        # 更新进度
        await WordVideoTask.update_progress(
            task_id=task_id,
            status="completed" if result.get("final_video_url") else "failed",
            progress=100,
            video_url=result.get("final_video_url"),
        )
```

### 4.8 第八步：新增数据模型

**新增文件**: `app/models/word_video.py`

```python
from sqlalchemy import Column, Integer, String, JSONB, DateTime
from sqlalchemy.sql import func
from app.db.base import Base

class WordVideoTask(Base):
    """英语单词视频任务"""
    __tablename__ = "word_video_tasks"
    
    task_id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), unique=True, index=True)
    
    # 用户
    user_id = Column(Integer, nullable=False, index=True)
    
    # 配置
    words = Column(JSONB, nullable=False)        # ["apple", "banana"]
    voice_gender = Column(String(10))
    voice_age = Column(String(10))
    sentence_level = Column(String(20))
    
    # 状态
    status = Column(String(20), default="processing")  # processing/completed/failed
    progress = Column(Integer, default=0)            # 0-100
    current_step = Column(String(50))               # 当前步骤描述
    video_url = Column(String(500))                # 最终视频URL
    error_message = Column(String(500))
    
    # 关联
    creation_id = Column(Integer)                  # 关联的Creation ID
    
    # 时间
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    @classmethod
    async def create(cls, user_id: int, **kwargs):
        # 异步创建逻辑
        pass
    
    @classmethod
    async def get_by_task_id(cls, task_id: str, user_id: int):
        # 查询逻辑
        pass
    
    @classmethod
    async def update_progress(cls, task_id: str, **kwargs):
        # 更新进度逻辑
        pass
```

---

## 五、聊天触发流程

### 5.1 流程图

```
用户: "帮我生成一个英语单词视频，包含 apple, banana, orange"
                    │
                    ▼
┌─────────────────────────────────────────┐
│          DialogueGraph                  │
│  entry → intent_detection               │
└─────────────────────┬───────────────────┘
                      │
                      ▼ 检测到 "word_video"
┌─────────────────────────────────────────┐
│    intent: create_word_video            │
│    details: {words: [apple, banana]}    │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│       BusinessSubgraph                  │
│  business_router → execute_worker       │
└─────────────────────┬───────────────────┘
                      │
                      ▼ creation_type="word_video"
┌─────────────────────────────────────────┐
│       WordVideoWorker                  │
│  生成展示分镜 → 生成解释分镜 → 导出       │
└─────────────────────┬───────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────┐
│          完成，返回视频URL               │
└─────────────────────────────────────────┘
```

### 5.2 意图识别示例

| 用户消息 | 识别意图 | details |
|---------|---------|---------|
| "生成英语单词视频" | create_word_video | 需引导用户提供单词 |
| "apple, banana, orange 这几个单词" | create_word_video | `{"words": ["apple", "banana", "orange"]}` |
| "帮我讲解 apple 这个单词" | create_word_video | `{"words": ["apple"]}` |
| "继续"（已配置单词） | generate_word_video | 开始生成 |

---

## 六、文件变更清单

### 6.1 新增文件 (5个)

| 文件 | 说明 |
|------|------|
| `app/models/word_video.py` | 单词视频任务模型 |
| `app/agent/workers/base_worker.py` | Worker基类 |
| `app/agent/workers/word_video_worker.py` | 单词视频Worker |
| `app/agent/triggers/api_trigger.py` | API触发器 |
| `app/api/api_v1/endpoints/word_video.py` | API端点 |

### 6.2 修改文件 (6个)

| 文件 | 修改内容 |
|------|---------|
| `app/agent/state/schemas.py` | 新增CreationType枚举 |
| `app/agent/prompts/intent_detection.md` | 新增意图类型 |
| `app/agent/graph/nodes/intent_detection.py` | 新增解析逻辑 |
| `app/agent/graph/comic_drama_subgraph.py` | 改造为BusinessSubgraph |
| `app/agent/graph/runner.py` | 新增execute_word_video方法 |
| `app/api/api_v1/api.py` | 注册word_video路由 |

### 6.3 新增提示词文件

| 文件 | 说明 |
|------|------|
| `app/agent/prompts/word_video_display.md` | 单词展示提示词 |
| `app/agent/prompts/word_video_explanation.md` | 单词解释提示词 |

---

## 七、实现顺序

1. **数据模型** → `app/models/word_video.py`
2. **状态定义** → `app/agent/state/schemas.py`
3. **Worker基类** → `app/agent/workers/base_worker.py`
4. **单词视频Worker** → `app/agent/workers/word_video_worker.py`
5. **意图识别** → `app/agent/prompts/intent_detection.md`
6. **业务子图改造** → `app/agent/graph/comic_drama_subgraph.py`
7. **Runner扩展** → `app/agent/graph/runner.py`
8. **API端点** → `app/api/api_v1/endpoints/word_video.py`
9. **API触发器** → `app/agent/triggers/api_trigger.py`

---

## 八、总结

### 8.1 核心改造点

1. **创作类型枚举**: 新增 `CreationType.WORD_VIDEO`
2. **通用Worker**: 实现 `BaseWorker` + `WorkerRegistry`
3. **单词视频Worker**: 实现完整的生成逻辑
4. **业务子图**: 从漫剧专用改为通用调度
5. **API触发**: 复用GraphRunner，支持直接执行

### 8.2 扩展性

未来新增其他创作类型（如绘本、诗歌）时：
1. 在 `CreationType` 枚举中添加新类型
2. 创建对应的Worker类
3. 在WorkerRegistry中注册
4. 无需修改核心逻辑

### 8.3 复用度

- **DialogueGraph**: 几乎不用改
- **GraphRunner**: 只需扩展 `execute_word_video`
- **视频生成工具**: 完全复用
- **导出工具**: 完全复用
