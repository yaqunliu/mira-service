# 单词视频 (Vocabulary Video) 功能实现规划

## 一、整体架构概览

在现有的 Mira 系统之上新增一层 **VocabVideo Agent**，复用现有的 Celery 异步任务框架、US3 存储、TTS 语音、AI 图片/视频生成和 FFmpeg 合成能力。

```
┌─────────────────────────────────────────────────────────┐
│                      API Layer                          │
│  POST /vocab-video/create   → 提交任务(返回纯数字ID)     │
│  GET  /vocab-video/{id}/progress → 查询进度/下载链接     │
│  GET  /vocab-video/{id}/download → 下载视频              │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│              VocabVideo Service Layer                    │
│  - 参数校验、任务创建、进度查询、结果返回                  │
│  - 将任务派发到 Celery                                   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│          Celery Task: vocab_video_generation_task        │
│                                                         │
│  Step 1: LLM 分析单词 (词性判断、翻译、造句)              │
│  Step 2: 批量生成素材 (背景图、名词圆圈图、解释场景视频)   │
│  Step 3: TTS 语音合成 (单词朗读 + 翻译朗读 + 句子配音)    │
│  Step 4: FFmpeg 合成最终视频                              │
└─────────────────────────────────────────────────────────┘
```

---

## 二、数据模型设计

### 2.1 新增 `VocabVideoTask` 模型

```python
# app/models/vocab_video.py

class VocabVideoTask(Base):
    __tablename__ = "vocab_video_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)  # 纯数字ID
    uuid = Column(String(36), unique=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)

    # 配置参数
    words = Column(JSONB, nullable=False)          # ["apple", "run", "happy", ...]
    word_count = Column(Integer, nullable=False)    # 3-5
    voice_gender = Column(String(10), nullable=False, default="female")  # male/female
    voice_age = Column(String(10), nullable=False, default="adult")      # child/adult
    sentence_difficulty = Column(String(20), nullable=False, default="primary_school")
    # 可选值: kindergarten / primary_school / middle_school

    # 状态与进度
    status = Column(String(20), default="pending")
    # pending → processing → completed → failed
    progress = Column(Integer, default=0)           # 0-100
    current_step = Column(String(50), nullable=True) # 当前步骤描述
    error_message = Column(Text, nullable=True)

    # 生成结果
    video_url = Column(String(500), nullable=True)  # 最终视频 US3 URL
    extra_data = Column(JSONB, nullable=True)        # 中间产物、分步结果

    # Celery 任务追踪
    celery_task_id = Column(String(100), nullable=True)

    # 时间戳
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime, nullable=True)

    # 关联
    owner = relationship("User", backref="vocab_video_tasks")
```

### 2.2 `extra_data` JSONB 结构

```json
{
  "words_analysis": [
    {
      "word": "apple",
      "translation": "苹果",
      "pos": "noun",
      "is_noun": true,
      "sentence": "I like to eat a red apple.",
      "sentence_translation": "我喜欢吃红苹果。"
    }
  ],
  "steps": {
    "word_analysis": { "status": "success", "updatedAt": "..." },
    "background_generation": { "status": "processing", "progress": 60 },
    "noun_circle_generation": { "status": "idle" },
    "scene_video_generation": { "status": "idle" },
    "tts_generation": { "status": "idle" },
    "video_composition": { "status": "idle" }
  },
  "assets": {
    "backgrounds": ["us3://bg_1.png", "us3://bg_2.png"],
    "noun_circles": {"apple": "us3://circle_apple.png"},
    "scene_videos": {"apple": "us3://scene_apple.mp4"},
    "word_audios": {"apple": "us3://word_apple.mp3"},
    "translation_audios": {"apple": "us3://trans_apple.mp3"},
    "sentence_audios": {"apple": "us3://sentence_apple.mp3"}
  },
  "character_used": {
    "apple": "character_3"
  }
}
```

---

## 三、API 设计

### 3.1 API 1：提交生成任务

```
POST /api/v1/vocab-video/create
```

**请求体:**
```json
{
  "words": ["apple", "run", "happy"],
  "voice_gender": "female",       // male | female
  "voice_age": "adult",           // child | adult
  "sentence_difficulty": "primary_school"  // kindergarten | primary_school | middle_school
}
```

**响应 (即时返回):**
```json
{
  "task_id": 10001,    // 纯数字
  "status": "pending",
  "message": "任务已创建，正在排队处理"
}
```

**校验规则:**
- `words` 长度 3-5 个
- 每个 word 为合法英文单词字符串
- `voice_gender` 枚举 male/female
- `voice_age` 枚举 child/adult
- `sentence_difficulty` 枚举 kindergarten/primary_school/middle_school

### 3.2 API 2：查询进度

```
GET /api/v1/vocab-video/{task_id}/progress
```

**处理中响应:**
```json
{
  "task_id": 10001,
  "status": "processing",
  "progress": 45,
  "current_step": "正在生成场景视频 (2/3)",
  "steps": {
    "word_analysis": "success",
    "background_generation": "success",
    "noun_circle_generation": "success",
    "scene_video_generation": "processing",
    "tts_generation": "idle",
    "video_composition": "idle"
  }
}
```

**完成响应:**
```json
{
  "task_id": 10001,
  "status": "completed",
  "progress": 100,
  "video_url": "/api/v1/vocab-video/10001/download",
  "video_direct_url": "https://us3.xxx.com/vocab_videos/xxx.mp4"
}
```

### 3.3 API 3：视频下载

```
GET /api/v1/vocab-video/{task_id}/download
```

- 返回视频文件流（`Content-Type: video/mp4`）
- 或 302 重定向到 US3 签名 URL

---

## 四、Celery 任务管线设计

### `vocab_video_generation_task`

```python
# app/tasks/vocab_video_task.py

@celery_app.task(bind=True, name="vocab_video_generation_task",
                 max_retries=2, autoretry_for=(Exception,),
                 retry_backoff=True)
def vocab_video_generation_task(self, task_id: int):
    """单词视频生成主任务 - 包含全部 6 个步骤"""

    # Step 1: LLM 分析单词 (10%)
    #   - 输入: words 列表
    #   - 输出: 每个单词的翻译、词性(是否名词)、造句
    #   - 更新 extra_data.words_analysis

    # Step 2: 生成多彩抽象背景图 (20%)
    #   - 为每个单词生成一张绚烂的多彩抽象背景图
    #   - 使用 AI 文生图（doubao-seedream）
    #   - Prompt: "Abstract colorful background, vibrant gradient, no objects..."
    #   - 上传到 US3

    # Step 3: 名词圆圈图生成 (30%)
    #   - 仅对 is_noun=true 的单词
    #   - 生成白色背景圆圈中的名词物品图
    #   - Prompt: "A [noun] on white background, centered in a circle, cartoon style..."
    #   - 上传到 US3

    # Step 4: 解释场景视频生成 (55%)
    #   - 对每个单词的句子
    #   - 使用固定角色(5选1) + 生成场景视频
    #   - 使用已有角色参考图（不重新生成角色）
    #   - 使用已有场景/或生成简单卡通场景背景
    #   - 调用 AI 视频生成 API
    #   - 上传到 US3

    # Step 5: TTS 语音合成 (75%)
    #   - 对每个单词:
    #     - 单词朗读 × 2 遍
    #     - 翻译朗读 × 1 遍
    #     - 句子配音 × 1 遍
    #   - 使用 FishAudio TTS
    #   - 根据配置选择男声/女声、儿童/成人

    # Step 6: FFmpeg 合成最终视频 (100%)
    #   - 循环: [单词展示片段, 单词解释片段, ...]
    #   - 单词展示: 背景图 + 白色无衬线字体 + 翻译 + 名词圆圈(可选) + 音频
    #   - 单词解释: 场景视频 + 顶部句子文字 + 句子配音
    #   - 硬字幕烧录
    #   - 输出最终 MP4 → 上传 US3
```

---

## 五、分镜支持使用预生成角色和场景

### 5.1 核心改造点

在现有的分镜拆分逻辑中增加对 **预设角色 / 预设场景** 的支持：

```python
# 分镜配置中新增字段
class ShotConfig:
    use_preset_character: bool = False      # 是否使用预设角色
    preset_character_id: str = None         # 预设角色标识 (char_1 ~ char_5)
    preset_character_image_url: str = None  # 预设角色参考图 URL

    use_preset_scene: bool = False          # 是否使用预设场景
    preset_scene_image_url: str = None      # 预设场景背景 URL

    skip_character_generation: bool = False # 跳过角色图生成
    skip_scene_generation: bool = False     # 跳过场景图生成
```

### 5.2 在 AI 视频生成时使用参考图

当 `use_preset_character=True` 时：
- 跳过角色分析和角色图生成步骤
- 直接将 `preset_character_image_url` 作为视频生成的角色参考图
- 视频提示词中包含角色外观描述（来自预设角色的固定描述）

当 `use_preset_scene=True` 时：
- 跳过场景图生成步骤
- 直接使用 `preset_scene_image_url` 作为场景背景

---

## 六、五个固定角色设计

### 角色设计原则
- 卡通风格，色彩鲜明
- 五个角色差异最大化（性别、年龄、肤色、服装、发型）
- 适合教育/儿童场景
- 每个角色有清晰的视觉辨识度

### 角色 1: Milo (男孩)
**生成提示词：**
```
Character design sheet, cartoon style, a cheerful 8-year-old boy named Milo.
Light skin, short messy brown hair, big round green eyes, freckles on cheeks.
Wearing a bright red hoodie with a star patch, blue jeans, and white sneakers.
Energetic and curious expression. Simple clean lines, vibrant colors,
children's educational animation style. Full body front view, white background,
character reference sheet.
```

### 角色 2: Luna (女孩)
**生成提示词：**
```
Character design sheet, cartoon style, a smart 9-year-old girl named Luna.
Medium brown skin, long curly black hair in two pigtails with yellow ribbons,
big warm brown eyes, round glasses. Wearing a purple cardigan over a white dress
with polka dots, pink mary jane shoes. Thoughtful and friendly expression.
Simple clean lines, vibrant colors, children's educational animation style.
Full body front view, white background, character reference sheet.
```

### 角色 3: Kai (男孩)
**生成提示词：**
```
Character design sheet, cartoon style, an adventurous 10-year-old boy named Kai.
East Asian features, tan skin, spiky black hair with a small blue streak,
bright dark eyes, confident smile. Wearing an orange safari vest over a green
t-shirt, khaki cargo shorts, brown hiking boots. Brave and determined expression.
Simple clean lines, vibrant colors, children's educational animation style.
Full body front view, white background, character reference sheet.
```

### 角色 4: Zara (女孩)
**生成提示词：**
```
Character design sheet, cartoon style, a creative 8-year-old girl named Zara.
Dark brown skin, short afro hair with a teal headband, sparkling dark brown eyes,
wide bright smile. Wearing a yellow painter's smock over a teal striped shirt,
denim overalls, red rain boots. Artistic and joyful expression.
Simple clean lines, vibrant colors, children's educational animation style.
Full body front view, white background, character reference sheet.
```

### 角色 5: Felix (男孩)
**生成提示词：**
```
Character design sheet, cartoon style, a gentle 9-year-old boy named Felix.
Fair skin, wavy ginger/red hair, soft blue eyes, rosy cheeks, shy gentle smile.
Wearing a cozy mint green sweater with a bear patch, brown corduroy pants,
navy blue canvas shoes, carrying a small backpack with books. Calm and kind
expression. Simple clean lines, vibrant colors, children's educational
animation style. Full body front view, white background, character reference sheet.
```

### 角色元数据 (代码中使用)

```python
# app/core/vocab_characters.py

VOCAB_CHARACTERS = {
    "char_1": {
        "name": "Milo",
        "gender": "male",
        "age": 8,
        "description": "A cheerful boy with short messy brown hair, green eyes, "
                       "freckles, wearing a red hoodie with a star patch and blue jeans.",
        "image_url": "",   # 生成后填入 US3 URL
        "video_prompt_desc": "a cheerful cartoon boy with messy brown hair, green eyes, "
                             "freckles, red hoodie with star patch, blue jeans, white sneakers"
    },
    "char_2": {
        "name": "Luna",
        "gender": "female",
        "age": 9,
        "description": "A smart girl with curly black pigtails, yellow ribbons, "
                       "round glasses, wearing a purple cardigan and white polka dot dress.",
        "image_url": "",
        "video_prompt_desc": "a smart cartoon girl with curly black pigtails, yellow ribbons, "
                             "round glasses, purple cardigan, white polka dot dress, pink shoes"
    },
    "char_3": {
        "name": "Kai",
        "gender": "male",
        "age": 10,
        "description": "An adventurous boy with spiky black hair with blue streak, "
                       "wearing an orange safari vest over green t-shirt.",
        "image_url": "",
        "video_prompt_desc": "an adventurous cartoon boy with spiky black hair with blue streak, "
                             "orange safari vest, green t-shirt, khaki cargo shorts, brown boots"
    },
    "char_4": {
        "name": "Zara",
        "gender": "female",
        "age": 8,
        "description": "A creative girl with short afro hair and teal headband, "
                       "wearing a yellow painter's smock and denim overalls.",
        "image_url": "",
        "video_prompt_desc": "a creative cartoon girl with short afro hair, teal headband, "
                             "yellow painter smock, denim overalls, red rain boots"
    },
    "char_5": {
        "name": "Felix",
        "gender": "male",
        "age": 9,
        "description": "A gentle boy with wavy ginger hair, blue eyes, "
                       "wearing a mint green sweater with bear patch.",
        "image_url": "",
        "video_prompt_desc": "a gentle cartoon boy with wavy ginger hair, blue eyes, rosy cheeks, "
                             "mint green sweater with bear patch, brown corduroy pants"
    }
}

def get_random_character(gender: str = None) -> dict:
    """随机选择角色，可指定性别"""
    import random
    candidates = VOCAB_CHARACTERS.values()
    if gender:
        candidates = [c for c in candidates if c["gender"] == gender]
    return random.choice(list(candidates))
```

---

## 七、LLM 提示词设计

### 7.1 单词分析提示词

```python
WORD_ANALYSIS_PROMPT = """
你是一位专业的英语教学专家。请分析以下英语单词列表，为每个单词提供：

1. 中文翻译
2. 词性 (noun/verb/adjective/adverb/preposition/other)
3. 是否为名词 (true/false)
4. 用这个单词造一个句子（难度级别：{difficulty}）
5. 句子的中文翻译

难度标准：
- kindergarten(幼儿园)：3-5个单词的简单句，常见词汇
- primary_school(小学)：5-8个单词的句子，基础语法
- middle_school(中学)：8-15个单词的复杂句，包含从句或复杂语法

单词列表：{words}

请以 JSON 格式返回：
[
  {{
    "word": "apple",
    "translation": "苹果",
    "pos": "noun",
    "is_noun": true,
    "sentence": "I like to eat a red apple.",
    "sentence_translation": "我喜欢吃红苹果。"
  }}
]
"""
```

### 7.2 多彩背景生成提示词

```python
COLORFUL_BG_PROMPT = """
Abstract colorful gradient background, vibrant swirling colors,
no objects, no text, no patterns, purely color composition,
bright and cheerful mood, soft flowing color transitions,
{color_theme} color palette, dreamy artistic abstract,
high resolution, suitable for children's educational content.
"""

# 为每个单词随机选择不同的配色方案
COLOR_THEMES = [
    "warm sunset orange and pink",
    "ocean blue and turquoise green",
    "purple galaxy and magenta",
    "spring green and golden yellow",
    "coral red and sky blue",
    "lavender purple and mint green",
    "tropical orange and lime green",
]
```

### 7.3 名词圆圈图生成提示词

```python
NOUN_CIRCLE_PROMPT = """
A cute cartoon {noun} illustration, centered inside a perfect circle,
white clean background, simple flat design, bright vivid colors,
children's book illustration style, no text, no shadow,
single object, high quality, educational content style.
"""
```

### 7.4 解释场景视频提示词

```python
SCENE_VIDEO_PROMPT = """
Cartoon animation style, {character_desc},
{scene_description},
bright cheerful atmosphere, children's educational video,
smooth simple animation, clean colorful visuals.
"""

# scene_description 由 LLM 根据句子生成
SCENE_DESCRIPTION_PROMPT = """
根据以下英文句子，描述一个适合卡通动画的场景画面（用英文描述）：

句子: "{sentence}"
角色: {character_name} - {character_desc}

要求:
1. 描述角色在做什么动作
2. 描述场景环境
3. 适合儿童观看的卡通风格
4. 简洁明了，不超过50个英文单词

返回格式: 直接返回场景描述文本
"""
```

---

## 八、视频合成规格

### 8.1 视频参数
```
分辨率: 1080 x 1920 (竖屏 9:16) 或 1920 x 1080 (横屏 16:9，可配置)
帧率: 30fps
编码: H.264
音频: AAC 128kbps
```

### 8.2 单词展示片段结构 (每个约 5-8 秒)

```
┌────────────────────────────┐
│          (名词圆圈)     ○  │  ← 右上角，仅名词出现
│                            │
│     ┌──────────────┐       │
│     │  多彩渐变背景  │       │
│     │              │       │
│     │    apple     │       │  ← 白色无衬线体(如 Montserrat Bold)
│     │    苹 果     │       │  ← 白色翻译文字，字号稍小
│     │              │       │
│     └──────────────┘       │
│                            │
└────────────────────────────┘

音频时序:
[0.0s] "apple" (朗读第1遍)
[1.5s] "apple" (朗读第2遍, 可配置)
[3.0s] "苹果"  (翻译朗读)
[4.5s] 结束
```

### 8.3 单词解释片段结构 (每个约 3-5 秒)

```
┌────────────────────────────┐
│  I like to eat a red apple.│  ← 顶部句子文字
│  我喜欢吃红苹果。           │  ← 中文翻译
│                            │
│  ┌──────────────────────┐  │
│  │                      │  │
│  │   卡通场景视频内容     │  │  ← AI 生成的卡通动画
│  │   (角色+场景)         │  │
│  │                      │  │
│  └──────────────────────┘  │
│                            │
└────────────────────────────┘

音频: 句子的 TTS 配音
```

### 8.4 FFmpeg 合成流程

```
1. 为每个单词生成「单词展示片段」:
   - 将多彩背景图拉伸为视频(静态图→视频)
   - 叠加白色单词文字 (drawtext filter)
   - 叠加翻译文字
   - 如果是名词，叠加右上角圆圈图 (overlay filter)
   - 叠加音频 (单词朗读×2 + 翻译朗读×1)

2. 为每个单词取得「解释场景片段」:
   - 在 AI 生成视频的顶部叠加句子文字
   - 叠加句子配音

3. 将所有片段按顺序拼接:
   word1_display → word1_explain → word2_display → word2_explain → ...

4. 添加片段间的渐变转场 (xfade filter, 0.5s)

5. 输出最终视频
```

---

## 九、TTS 语音配置

### 声音选择矩阵

```python
VOICE_CONFIG = {
    ("female", "adult"): {
        "voice_id": "对应 FishAudio 或 TTS 服务的 voice_id",
        "description": "成人女声，温柔清晰"
    },
    ("female", "child"): {
        "voice_id": "...",
        "description": "儿童女声，活泼可爱"
    },
    ("male", "adult"): {
        "voice_id": "...",
        "description": "成人男声，稳重亲和"
    },
    ("male", "child"): {
        "voice_id": "...",
        "description": "儿童男声，阳光活力"
    },
}
```

生成规则:
- 英文单词朗读: 使用英文 TTS
- 中文翻译朗读: 使用中文 TTS（同一音色的中文版本）
- 句子配音: 使用英文 TTS

---

## 十、需要新增/修改的文件清单

### 新增文件

| 文件路径 | 说明 |
|---------|------|
| `app/models/vocab_video.py` | VocabVideoTask 数据模型 |
| `app/schemas/vocab_video.py` | Pydantic 请求/响应 Schema |
| `app/api/api_v1/endpoints/vocab_video.py` | 3 个 API 端点 |
| `app/services/vocab_video_service.py` | 业务逻辑 Service |
| `app/services/vocab_video_async_service.py` | 异步版 Service (API 层用) |
| `app/tasks/vocab_video_task.py` | Celery 主生成任务 |
| `app/core/vocab_characters.py` | 5 个固定角色数据 + 随机选取逻辑 |
| `app/prompt/vocab_video_prompts.py` | 所有 LLM / 图片 / 视频提示词 |
| `migrations/versions/xxx_add_vocab_video_tasks.py` | 数据库迁移 |

### 修改文件

| 文件路径 | 修改内容 |
|---------|---------|
| `app/api/api_v1/api.py` | 注册 vocab_video router |
| `app/core/celery_app.py` | include 新增的 task 模块 |
| `app/models/__init__.py` | 导入 VocabVideoTask 模型 |

---

## 十一、实施步骤

### Phase 1: 基础框架 (数据模型 + API + 任务骨架)
1. 创建 `VocabVideoTask` 模型 + 数据库迁移
2. 创建 Schema (请求/响应)
3. 实现 3 个 API 端点 (创建任务/查询进度/下载视频)
4. 创建 Service 层
5. 创建 Celery 任务骨架 (空步骤，仅更新进度)
6. 注册路由和任务到 Celery

### Phase 2: LLM 单词分析
7. 实现单词分析提示词
8. 调用 LLM API 进行分析
9. 解析并存储分析结果到 `extra_data`

### Phase 3: 素材生成
10. 实现多彩背景图生成 (AI 文生图)
11. 实现名词圆圈图生成 (AI 文生图)
12. 实现固定角色系统 (`vocab_characters.py`)
13. 实现解释场景描述生成 (LLM)
14. 实现解释场景视频生成 (AI 文生视频, 使用固定角色参考图)

### Phase 4: 语音合成
15. 实现 TTS 语音生成 (单词/翻译/句子)
16. 实现声音配置选择 (男/女、儿童/成人)

### Phase 5: 视频合成
17. 实现单词展示片段 FFmpeg 合成
18. 实现单词解释片段 FFmpeg 合成
19. 实现最终视频拼接 + 转场
20. 上传到 US3 并更新状态

### Phase 6: 测试与优化
21. 端到端测试
22. 错误处理和重试机制
23. 进度更新优化

---

## 十二、关于分镜拆解支持预设角色/场景

本方案中单词视频的「解释场景」段直接使用 5 个固定角色，不走传统的角色分析+生成流程。具体做法：

1. **角色参考图预生成**: 使用上面设计的 5 个角色提示词，提前生成角色参考图并上传到 US3，URL 写入 `VOCAB_CHARACTERS` 配置。

2. **场景视频生成时传入角色参考图**: 在调用 AI 视频生成 API 时，附带角色参考图 URL，使 AI 在视频中保持角色外观一致性。

3. **跳过角色和场景的生成步骤**: 不调用 `character_analysis_task` 也不调用 `scene_analysis_task`，直接进行视频提示词生成和视频生产。

4. **随机分配角色**: 为每个单词的解释场景随机选择一个角色（保证性别与句子内容匹配，如句子中有 boy/he 则选男性角色）。

这个设计是在现有 Agent 之上新加的一层，不改动现有的创作流程，完全独立运行。
