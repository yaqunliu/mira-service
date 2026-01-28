# Agent 知识库

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
