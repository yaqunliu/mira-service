# Agent 知识库
```uv run python -c "from app.agent.knowledge.init_knowledge import init_knowledge; init_knowledge()"

Using CPython 3.13.9 interpreter at: /opt/miniconda3/bin/python3
Removed virtual environment at: .venv
Creating virtual environment at: .venv
Installed 169 packages in 1.23s
2026-01-29 11:49:05.622 | INFO     | app.agent.knowledge.base:__init__:48 - 知识库初始化完成: style_knowledge (embedding: text-embedding-ada-002)
2026-01-29 11:49:05.654 | INFO     | app.agent.knowledge.base:__init__:48 - 知识库初始化完成: director_knowledge (embedding: text-embedding-ada-002)
2026-01-29 11:49:05.681 | INFO     | app.agent.knowledge.base:__init__:48 - 知识库初始化完成: prompt_knowledge (embedding: text-embedding-ada-002)
2026-01-29 11:49:05.709 | INFO     | app.agent.knowledge.base:__init__:48 - 知识库初始化完成: storyboard_knowledge (embedding: text-embedding-ada-002)
2026-01-29 11:49:05.709 | INFO     | app.agent.knowledge.init_knowledge:init_all:405 - 清空现有知识库...
2026-01-29 11:49:05.711 | INFO     | app.agent.knowledge.init_knowledge:clear_all_knowledge:390 - 已删除集合: style_knowledge
2026-01-29 11:49:05.713 | INFO     | app.agent.knowledge.init_knowledge:clear_all_knowledge:390 - 已删除集合: director_knowledge
2026-01-29 11:49:05.714 | INFO     | app.agent.knowledge.init_knowledge:clear_all_knowledge:390 - 已删除集合: prompt_knowledge
2026-01-29 11:49:05.715 | INFO     | app.agent.knowledge.init_knowledge:clear_all_knowledge:390 - 已删除集合: storyboard_knowledge
2026-01-29 11:49:05.741 | INFO     | app.agent.knowledge.base:__init__:48 - 知识库初始化完成: style_knowledge (embedding: text-embedding-ada-002)
2026-01-29 11:49:05.774 | INFO     | app.agent.knowledge.base:__init__:48 - 知识库初始化完成: director_knowledge (embedding: text-embedding-ada-002)
2026-01-29 11:49:05.798 | INFO     | app.agent.knowledge.base:__init__:48 - 知识库初始化完成: prompt_knowledge (embedding: text-embedding-ada-002)
2026-01-29 11:49:05.821 | INFO     | app.agent.knowledge.base:__init__:48 - 知识库初始化完成: storyboard_knowledge (embedding: text-embedding-ada-002)
2026-01-29 11:49:05.822 | INFO     | app.agent.knowledge.init_knowledge:init_all:413 - 开始初始化知识库...
2026-01-29 11:49:05.823 | INFO     | app.agent.knowledge.init_knowledge:init_style_knowledge:228 - 解析 visual_styles.md: 7 个风格
2026-01-29 11:49:05.823 | INFO     | app.agent.knowledge.init_knowledge:init_style_knowledge:235 - 解析 color_psychology.md: 6 个色彩类型
2026-01-29 11:49:07.883 | INFO     | app.agent.knowledge.base:add_documents:90 - 添加 13 个文档到知识库
2026-01-29 11:49:07.885 | INFO     | app.agent.knowledge.init_knowledge:init_director_knowledge:260 - 解析 camera_techniques.md: 8 个镜头类型
2026-01-29 11:49:07.886 | INFO     | app.agent.knowledge.init_knowledge:init_director_knowledge:269 - 解析 composition.md: 7 个构图技巧
2026-01-29 11:49:07.886 | INFO     | app.agent.knowledge.init_knowledge:init_director_knowledge:278 - 解析 lighting_mood.md: 3 个光线技巧
2026-01-29 11:49:07.886 | INFO     | app.agent.knowledge.init_knowledge:init_director_knowledge:287 - 解析 pacing_editing.md: 5 个剪辑技巧
2026-01-29 11:49:07.886 | INFO     | app.agent.knowledge.init_knowledge:init_director_knowledge:296 - 解析 storyboard_techniques.md: 8 个分镜技巧
2026-01-29 11:49:09.920 | INFO     | app.agent.knowledge.base:add_documents:90 - 添加 31 个文档到知识库
2026-01-29 11:49:09.922 | INFO     | app.agent.knowledge.init_knowledge:init_prompt_knowledge:323 - 解析 character_prompts.md: 5 个模板
2026-01-29 11:49:09.922 | INFO     | app.agent.knowledge.init_knowledge:init_prompt_knowledge:332 - 解析 scene_prompts.md: 6 个模板
2026-01-29 11:49:09.922 | INFO     | app.agent.knowledge.init_knowledge:init_prompt_knowledge:341 - 解析 storyboard_prompts.md: 5 个模板
2026-01-29 11:49:11.031 | INFO     | app.agent.knowledge.base:add_documents:90 - 添加 16 个文档到知识库
2026-01-29 11:49:11.868 | INFO     | app.agent.knowledge.base:add_documents:90 - 添加 8 个文档到知识库
2026-01-29 11:49:11.868 | INFO     | app.agent.knowledge.init_knowledge:init_knowledge:432 - ==================================================
2026-01-29 11:49:11.868 | INFO     | app.agent.knowledge.init_knowledge:init_knowledge:433 - 知识库初始化完成:
2026-01-29 11:49:11.869 | INFO     | app.agent.knowledge.init_knowledge:init_knowledge:439 -   ✓ style: 13 个文档
2026-01-29 11:49:11.869 | INFO     | app.agent.knowledge.init_knowledge:init_knowledge:439 -   ✓ director: 31 个文档
2026-01-29 11:49:11.869 | INFO     | app.agent.knowledge.init_knowledge:init_knowledge:439 -   ✓ prompt: 16 个文档
2026-01-29 11:49:11.869 | INFO     | app.agent.knowledge.init_knowledge:init_knowledge:439 -   ✓ storyboard: 8 个文档
2026-01-29 11:49:11.869 | INFO     | app.agent.knowledge.init_knowledge:init_knowledge:443 -   总计: 68 个文档
2026-01-29 11:49:11.869 | INFO     | app.agent.knowledge.init_knowledge:init_knowledge:444 - ==================================================

```
## 目录结构


```
knowledge/
├── director/          # 导演知识库
│   ├── storyboard_examples.md    # 分镜案例
│   ├── camera_techniques.md      # 镜头技巧
│   ├── composition_rules.md      # 构图法则
│   └── pacing_guide.md           # 节奏指南
│
├── prompts/           # 提示词规范
│   ├── character_prompt_guide.md # 角色提示词
│   ├── scene_prompt_guide.md     # 场景提示词
│   ├── storyboard_prompt_guide.md # 分镜提示词
│   └── video_prompt_guide.md     # 视频提示词
│
└── styles/            # 风格模板
    ├── anime_style.json
    ├── realistic_style.json
    └── cartoon_style.json
```

## 使用方式

知识库将被向量化后存储在 Chroma 数据库中，Agent 可通过 `query_knowledge` 工具查询相关知识。

### 示例：查询分镜技巧

```python
from app.agent.tools import query_knowledge

# 查询导演知识
results = await query_knowledge(
    question="如何设计动作场景的分镜？",
    category="director",
    k=3
)
```

## 待补充内容

- [ ] 导演知识文档
- [ ] 提示词规范文档
- [ ] 风格模板 JSON
