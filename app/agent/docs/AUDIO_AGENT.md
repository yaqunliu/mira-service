# Audio Agent 音频处理系统

> 漫画短剧生成系统的音频处理模块
> 包含 AudioAgent（音频生成）和 VoiceSelectionAgent（音色选择）

---

## 目录

1. [概述](#1-概述)
2. [AudioAgent 音频生成](#2-audioagent-音频生成)
3. [VoiceSelectionAgent 音色选择](#3-voiceselectionagent-音色选择)
4. [工具集](#4-工具集)
5. [LangGraph 集成](#5-langgraph-集成)
6. [最佳实践](#6-最佳实践)

---

## 1. 概述

### 1.1 系统架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Audio System                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────┐         ┌─────────────────────┐               │
│  │   AudioAgent        │         │ VoiceSelectionAgent │               │
│  │   (音频生成)         │         │   (音色选择)         │               │
│  └──────────┬──────────┘         └──────────┬──────────┘               │
│             │                               │                           │
│             ▼                               ▼                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        Tools Layer                               │   │
│  ├─────────────────┬─────────────────┬─────────────────────────────┤   │
│  │ GenerateAudio   │ AnalyzeEmotion  │ LoadVoiceList               │   │
│  │ WithEmotionTool │ Tool            │ MatchVoiceByAttributes      │   │
│  ├─────────────────┴─────────────────┴─────────────────────────────┤   │
│  │                     SaveAudioToShotTool                          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      External APIs                               │   │
│  ├─────────────────┬─────────────────┬─────────────────────────────┤   │
│  │   Fish Audio    │      US3        │      Voice Database          │   │
│  │   (TTS API)     │   (音频存储)     │      (音色缓存)              │   │
│  └─────────────────┴─────────────────┴─────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 功能对比

| 功能 | AudioAgent | VoiceSelectionAgent |
|------|------------|---------------------|
| 主要职责 | 生成音频 | 选择音色 |
| 输入 | 分镜文本 | 角色属性 |
| 输出 | 音频 URL | voice_id |
| Fish Audio 工具 | TTS 生成 | 音色列表查询 |
| 状态管理 | audio_segments | characters.voice_id |

---

## 2. AudioAgent 音频生成

### 2.1 简介

AudioAgent 负责为漫画短剧的各个分镜生成高质量音频。它集成了 Fish Audio API，支持：
- 64+ 情感标签
- 语速调节（0.5-2.0）
- 自动匹配角色声音
- 旁白自动选择音色

### 2.2 文件位置

```
mira-service/app/agent/agents/audio_agent.py
```

### 2.3 初始化

```python
from app.agent.agents.audio_agent import AudioAgent

audio_agent = AudioAgent()
```

### 2.4 核心方法

#### 2.4.1 generate_audio_for_shot

为单个分镜生成音频。

```python
result = await audio_agent.generate_audio_for_shot(
    state=state,
    shot_id=1,
    narration_index=0
)

# 返回结果示例
{
    "success": True,
    "message": "音频生成成功",
    "data": {
        "audio_url": "https://...",
        "duration": 5.2,
        "voice_id": "...",
        "emotion_tags": ["happy", "laughing"]
    }
}
```

**参数说明：**

| 参数 | 类型 | 说明 |
|------|------|------|
| state | ComicDramaState | 当前状态 |
| shot_id | int | 分镜 ID |
| narration_index | int | 旁白索引（默认 0） |

#### 2.4.2 generate_audio_for_all_shots

批量为多个分镜生成音频。

```python
result = await audio_agent.generate_audio_for_all_shots(
    state=state,
    scene_id=1,           # 可选：指定场景
    shot_ids=[1, 2, 3]    # 可选：指定分镜列表
)

# 返回结果示例
{
    "success": True,
    "message": "音频生成完成: 5 成功, 0 失败",
    "data": {
        "total": 5,
        "success_count": 5,
        "failed_count": 0,
        "results": [...]
    }
}
```

#### 2.4.3 analyze_script_audio_needs

分析剧本中的音频需求。

```python
result = await audio_agent.analyze_script_audio_needs(state=state)

# 返回结果示例
{
    "success": True,
    "data": {
        "narration_count": 10,
        "character_dialogue_count": 25,
        "total_duration_estimate": 180.5,
        "estimated_cost": 0.45
    }
}
```

#### 2.4.4 review_generated_audio

审核已生成的音频。

```python
result = await audio_agent.review_generated_audio(
    state=state,
    shot_id=1
)

# 返回结果示例
{
    "success": True,
    "data": {
        "is_valid": True,
        "duration_match": True,
        "audio_quality": "good",
        "suggestions": []
    }
}
```

#### 2.4.5 recommend_voice_config

推荐语音配置。

```python
result = await audio_agent.recommend_voice_config(
    state=state,
    character_name="丁真"
)

# 返回结果示例
{
    "success": True,
    "data": {
        "voice_id": "...",
        "voice_speed": "1.0",
        "recommended_emotions": ["calm", "gentle"],
        "reason": "根据角色性格推荐..."
    }
}
```

---

## 3. VoiceSelectionAgent 音色选择

### 3.1 简介

VoiceSelectionAgent 负责为角色选择最合适的 Fish Audio 音色。通过分析角色的属性（名称、描述、性格、年龄等），智能匹配合适的声音。

### 3.2 文件位置

```
mira-service/app/agent/agents/voice_selection_agent.py
```

### 3.3 初始化

```python
from app.agent.agents.voice_selection_agent import VoiceSelectionAgent

voice_agent = VoiceSelectionAgent()
```

### 3.4 核心方法

#### 3.4.1 select_voice_for_character

为单个角色选择音色。

```python
result = await voice_agent.select_voice_for_character(
    state=state,
    character_name="丁真",
    character_description="年轻、帅气的藏族男孩",
    character_personality="真诚、腼腆、善良",
    force_gender="male"  # 可选
)

# 返回结果示例
{
    "success": True,
    "data": {
        "voice": {
            "voice_id": "...",
            "title": "丁真",
            "description": "...",
            "tags": ["male", "young", "friendly", "calm", "gentle"]
        },
        "match_score": 85,
        "match_reasons": ["性别匹配：男声", "性格特点匹配：friendly, calm"]
    }
}
```

#### 3.4.2 select_voice_for_all_characters

批量为所有角色选择音色。

```python
result = await voice_agent.select_voice_for_all_characters(
    state=state,
    character_names=["丁真", "学姐"],  # 可选：指定角色
    skip_named_voices=True  # 跳过已有音色的角色
)

# 返回结果示例
{
    "success": True,
    "data": {
        "results": [
            {
                "character_name": "丁真",
                "status": "success",
                "voice": {...},
                "match_score": 85
            },
            ...
        ],
        "summary": {
            "total": 5,
            "success": 5,
            "failed": 0,
            "skipped": 0
        }
    }
}
```

#### 3.4.3 match_voice_by_attributes

根据属性直接匹配音色。

```python
result = await voice_agent.match_voice_by_attributes(
    state=state,
    gender="male",
    age_range="young",
    personality_traits=["friendly", "calm"],
    voice_quality=["clear"],
    language="zh"
)

# 返回结果示例
{
    "success": True,
    "data": {
        "matched_voices": [...],
        "total_candidates": 15
    }
}
```

#### 3.4.4 analyze_character_voice_needs

分析角色对音色的需求。

```python
result = await voice_agent.analyze_character_voice_needs(
    state=state,
    character_name="丁真",
    dialogues=["大家好，我是丁真。", "很高兴见到你们！"]
)

# 返回结果示例
{
    "success": True,
    "data": {
        "suggested_gender": "male",
        "suggested_age": "young",
        "suggested_personality": ["friendly", "calm", "gentle"],
        "suggested_voice_quality": ["clear", "soft"],
        "reasoning": "根据角色名称和描述分析..."
    }
}
```

#### 3.4.5 update_character_voice

更新角色的音色信息。

```python
result = await voice_agent.update_character_voice(
    state=state,
    character_name="丁真",
    voice_id="specific-voice-id",
    voice_speed="1.0"
)
```

---

## 4. 工具集

### 4.1 音频生成工具

#### GenerateAudioWithEmotionTool

生成带情感标签的音频。

```python
from app.agent.tools.audio_tools import GenerateAudioWithEmotionTool

tool = GenerateAudioWithEmotionTool()
result = await tool.execute(
    state=state,
    text="你好，这是测试语音",
    voice_id="...",           # 可选
    voice_speed=1.0,          # 可选：0.5-2.0
    emotion_tags=["happy"],   # 可选
    character_id=1,           # 可选
    shot_id=1                 # 可选
)
```

#### AnalyzeEmotionTool

分析文本情感并推荐标签。

```python
from app.agent.tools.audio_tools import AnalyzeEmotionTool

tool = AnalyzeEmotionTool()
result = await tool.execute(
    state=state,
    text="我真的太开心了！",
    context="角色正在庆祝生日"
)
```

#### GenerateShotAudioTool

为分镜生成音频。

```python
from app.agent.tools.audio_tools import GenerateShotAudioTool

tool = GenerateShotAudioTool()
result = await tool.execute(
    state=state,
    shot_id=1,
    narration_index=0,
    force_voice_id="..."  # 可选
)
```

#### SaveAudioToShotTool

保存音频到分镜记录。

```python
from app.agent.tools.audio_tools import SaveAudioToShotTool

tool = SaveAudioToShotTool()
result = await tool.execute(
    state=state,
    shot_id=1,
    audio_url="https://...",
    audio_type="dialogue",  # dialogue/narration/music/sfx
    narration_index=0
)
```

### 4.2 音色选择工具

#### LoadVoiceListTool

加载音色列表。

```python
from app.agent.tools.voice_selection_tools import LoadVoiceListTool

tool = LoadVoiceListTool()
result = tool.execute(
    state=state,
    voice_type="all",  # all/male/female
    include_tags=True
)
```

#### MatchVoiceByAttributesTool

根据属性匹配音色。

```python
from app.agent.tools.voice_selection_tools import MatchVoiceByAttributesTool

tool = MatchVoiceByAttributesTool()
result = tool.execute(
    state=state,
    gender="male",
    age_range="young",
    personality_traits=["friendly", "calm"],
    limit=5
)
```

#### SelectVoiceForCharacterTool

为单个角色选择音色。

```python
from app.agent.tools.voice_selection_tools import SelectVoiceForCharacterTool

tool = SelectVoiceForCharacterTool()
result = tool.execute(
    state=state,
    character_name="丁真",
    character_description="年轻男孩",
    character_personality="活泼开朗"
)
```

#### BatchSelectVoiceTool

批量选择音色。

```python
from app.agent.tools.voice_selection_tools import BatchSelectVoiceTool

tool = BatchSelectVoiceTool()
result = tool.execute(
    state=state,
    skip_named_voices=True
)
```

---

## 5. LangGraph 集成

### 5.1 音频处理节点

```python
from app.agent.graph.comic_drama_graph import (
    audio_processing_node,
    route_from_audio,
)
```

### 5.2 音色选择节点

```python
from app.agent.graph.voice_selection_nodes import (
    load_voice_list_node,
    batch_select_voice_node,
    should_select_voice,
)
```

### 5.3 工作流配置

```python
from langgraph.graph import StateGraph
from app.agent.state.schemas import ComicDramaState

# 构建音频处理图
def build_audio_graph():
    graph = StateGraph(ComicDramaState)
    
    graph.add_node("audio_processing", audio_processing_node)
    graph.add_node("review_audio", review_audio_node)
    
    graph.set_entry_point("audio_processing")
    graph.add_edge("audio_processing", "review_audio")
    graph.add_conditional_edges(
        "review_audio",
        route_from_audio,
        {
            "generate_video": "video_generation",
            "error": "handle_audio_error",
            "retry": "audio_processing"
        }
    )
    
    return graph.compile()
```

---

## 6. 最佳实践

### 6.1 角色命名建议

为获得更好的音色匹配，建议在角色名称中包含性别暗示：

| 类型 | 示例 | 说明 |
|------|------|------|
| 女性角色 | AD学姐、御姐茉莉、女大学生 | 包含"学姐"、"姐"、"女"等词 |
| 男性角色 | 丁真、郭德纲、雷军 | 包含性别暗示的名称 |

### 6.2 角色配置示例

```json
{
    "name": "丁真",
    "description": "20岁的藏族男孩，笑容纯真，眼神清澈",
    "personality": "腼腆、善良、友好、有些内向",
    "voice_id": "...",
    "voice_speed": "1.0"
}
```

### 6.3 情感标签使用

#### 基本情绪（24种）

| 标签 | 场景示例 |
|------|----------|
| (happy) | 打招呼、分享好消息 |
| (sad) | 传达坏消息、表达同情 |
| (angry) | 投诉、表达不满 |
| (excited) | 宣布好消息、庆祝 |
| (calm) | 叙述、指导、冥想 |
| (nervous) | 道歉、紧张场景 |

#### 高级情绪（25种，仅 S1 模型）

| 标签 | 场景示例 |
|------|----------|
| (disappointed) | 表达失望 |
| (grateful) | 感谢场景 |
| (curious) | 提问、探索 |
| (sarcastic) | 幽默吐槽 |

#### 语气标记（5种）

| 标签 | 说明 |
|------|------|
| (whispering) | 低声耳语 |
| (shouting) | 大声喊叫 |
| (soft tone) | 柔和语气 |

#### 音频效果（10种）

| 标签 | 说明 |
|------|------|
| (laughing) | 笑声 |
| (sobbing) | 哭泣 |
| (sighing) | 叹息 |

### 6.4 音色库

#### 中文音色统计

| 分类 | 数量 | 代表音色 |
|------|------|----------|
| 👨 男性 | 9 | 丁真、赛马娘、央视配音、郭德纲 |
| 👩 女性 | 8 | AD学姐、王琨、元気な女性 |
| ❓ 未分类 | 19 | 蔡徐坤、雷军、蒋介石 |

#### 推荐音色

| 性别 | 名称 | 特点 | 使用次数 |
|------|------|------|----------|
| 👨 | 丁真 | 年轻、温柔、真诚 | 390,534 |
| 👨 | 央视配音 | 专业、权威、清晰 | 124,223 |
| 👩 | AD学姐 | 女友感、御姐 | 288,716 |
| 👩 | 王琨 | 清晰、专业 | 120,307 |

### 6.5 批量处理建议

```python
# 推荐：先选择音色，再生成音频

# 1. 批量选择音色
voice_result = await voice_agent.select_voice_for_all_characters(
    state=state,
    skip_named_voices=True
)

# 2. 批量生成音频
audio_result = await audio_agent.generate_audio_for_all_shots(
    state=state
)
```

---

## 7. 常见问题

### Q1: 匹配度低怎么办？

检查角色属性是否完整，建议：
1. 完善角色描述
2. 明确指定 `force_gender`
3. 使用 `preferred_voice_ids` 预选

### Q2: 多个角色分配了相同音色？

系统会自动避免音色重复使用，如需特殊处理可手动指定。

### Q3: 情感标签不生效？

确保使用 S1 模型，旧模型仅支持基本情绪。

### Q4: 如何添加新音色？

更新 `docs/FISH_AUDIO_VOICES_CN.json` 文件即可。

---

## 8. 更新日志

| 日期 | 版本 | 说明 |
|------|------|------|
| 2026-01-31 | v1.0 | 初始版本，实现基础功能 |
| 2026-01-31 | v1.1 | 添加 VoiceSelectionAgent 文档 |
