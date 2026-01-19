"""
视频提示词生成工具
从 VideoGenerationPipeline 中提取出来的独立函数
"""
from typing import List, Dict
from app.core.logger import logger
from app.utils.ai_client import AIClient


def generate_video_prompt(
    llm_model: str,
    shot,
    script: str,
    dialogues: List[Dict[str, str]],
    characters: List[Dict[str, str]] = None,
    image_prompt: str = None
) -> str:
    """
    使用 LLM 生成详细的视频提示词（纯文本，不是JSON）
    """
    # 默认调用基础范式
    return _generate_video_prompt_internal(
        llm_model=llm_model,
        shot=shot,
        script=script,
        dialogues=dialogues,
        characters=characters,
        image_prompt=image_prompt,
        paradigm="standard"
    )


def generate_video_only_prompt(
    llm_model: str,
    shot,
    script: str,
    characters: List[Dict[str, str]] = None,
    image_prompt: str = None
) -> str:
    """
    生成纯视频提示词（无声、无台词，专注于运镜和动作）
    """
    return _generate_video_prompt_internal(
        llm_model=llm_model,
        shot=shot,
        script=script,
        dialogues=[], # 强制无台词
        characters=characters,
        image_prompt=image_prompt,
        paradigm="video_only"
    )


def _generate_video_prompt_internal(
    llm_model: str,
    shot,
    script: str,
    dialogues: List[Dict[str, str]],
    characters: List[Dict[str, str]] = None,
    image_prompt: str = None,
    paradigm: str = "standard"
) -> str:
    """
    内部统一生成函数
    """
    # 初始化 AIClient
    ai_client = AIClient(llm_model_name=llm_model)

    # 加载提示词模板
    try:
        system_prompt = ai_client._load_prompt_template("video_generation_v2")
        logger.info("成功加载视频提示词模板 v2")
        
        # 如果是 video_only 模式，在系统提示词后面添加额外指令
        if paradigm == "video_only":
            system_prompt += "\n\n**重要：当前为纯视频模式，请忽略所有台词和声音描述，不要在输出中包含任何音频相关的特征或内容。**"
    except Exception as e:
        logger.warning(f"加载视频提示词模板 v2 失败，使用内置模板: {e}")
        if paradigm == "video_only":
            system_prompt = """你是一个顶级的视频导演、运镜设计师和 AI 视频提示词专家。
请根据分镜描述和角色信息，按照以下“无声电影感视觉范式”生成提示词。
此提示词专门用于生成纯视频内容，严禁包含任何关于声音、台词、对话或发声角色的描述。

## 必须严格遵守的输出格式：

Style：[描述视觉风格。默认兜底设定：电影质感动画风格，具备精细的线条与写实光影，强调戏剧性高对比和角色表情纹理细节。]

[以自然语言撰写场景描述。描述角色、服装、场景、天气与其他细节。尽量具体一点，让生成出的影片更贴近想象。]

Characters：
On-screen Character：[描述画面中出现的角色及其视觉细节，需参考“图片提示词”以确保不遗漏画面中的关键人物。只需描述外观和神态，严禁描述声音。]

Cinematography：
Camera：[镜头类型与运动，如：中近景，缓慢推近 / 环绕镜头 / 低角度仰拍]
Lens：[虚拟焦距与景深效果，如：35mm，浅景深]
Lighting：[光影布局，如：侧逆光，暖色主光，强对比光影]
Mood：[情绪氛围，如：温情、悬疑、热血、宁静]

Actions：
– [时长: Xs] [运镜方式]：[人物角色] [具体视觉动作描述]，[神态变化]。例如：人物猛地抬头，眼神中流露出惊恐，双手紧握。
– [时长: Xs] [运镜方式]：[环境/特效/物体] [动态描述]。例如：背景中的火焰剧烈跳动，烟雾向右侧急速飘散。
– [最终画面状态描述]

## 输出规则：
- **严禁包含台词/声音**：绝对不要出现“说”、“喊”、“台词”、“声音”、“音效”等任何与听觉相关的词汇。
- **视觉驱动**：所有的情绪和剧情必须通过人物的【动作】、【神态】和【运镜】来表达。
- **全员自然动态**：画面中所有元素必须有明确的动态描述，严禁 PPT 感。
- **Style 保持一致**：默认使用电影质感动画风格。
- **仅输出中文文本**。
"""
        else:
            # 标准范式 (带声音) - 旧版兜底
            system_prompt = """你是一个顶级的视频导演、运镜设计师和 Sora 2 提示词专家。
请根据分镜描述、角色信息和台词，按照以下“结构化电影感范式”生成提示词。

## 必须严格遵守的输出格式：

Style：[描述视觉风格。默认兜底设定：电影质感动画风格，具备精细的线条与写实光影，强调戏剧性高对比和角色表情纹理细节。]

[以自然语言撰寫場景描述。描述角色、服裝、場景、天氣與其他細節。盡量具體一點，讓生成出的影片更貼近想像。]

Characters：
On-screen Character：[描述画面中出现的角色及其视觉细节，需参考“图片提示词”以确保不遗漏画面中的任何人（如路人、敌对阵营等）]
Voice Character：[描述发声的角色及其声音特质，如无说话角色则填：无]

Cinematography：
Camera：[镜头类型与运动，如：中近景，缓慢推近]
Lens：[虚拟焦距与景深效果，如：35mm，浅景深]
Lighting：[光影布局，如：侧逆光，暖色主光]
Mood：[情绪氛围，如：温情、悬疑、热血]

Actions：
– [时长: Xs] [运镜方式，如：切换镜头至人物特写 / 俯视转正视 / 快速推近]：[人物角色] [具体动作描述]，[表情/神态]。人物开口说：“[台词内容]”。
– [时长: Xs] [运镜方式]：[人物/环境/特效] [动态描述]，背景中的 [其他角色] 正在 [动作]。
– [最终状态描述]

Background Sound：
[环境音效描述，如：雨声、脚步声、机械嗡鸣，严禁包含 BGM/背景音乐]

## 输出规则
- **全员自然动态（拒绝PPT感）**：画面中出现的**所有人物**（无论主角还是背景路人）必须保持自然的生理微动。
- **Action 详情化**：每个 Action 必须包含明确的时长、运镜、人物、详尽动作、台词及表情。
- **音画同步**：Background Sound 必须与 Actions 呼应。
- **对话必现**：台词必须自然融入 Actions 的描述中。
- **严禁 BGM**：不得描述任何背景音乐或乐器。
"""

    # 格式化台词/旁白 (仅在非 video_only 模式下使用)
    dialogues_str = ""
    if paradigm != "video_only" and dialogues:
        dialogues_str = "\n".join([f"- {list(d.keys())[0]}: {list(d.values())[0]}" for d in dialogues])

    # 格式化角色信息
    characters_str = ""
    if characters:
        character_parts = []
        for char in characters:
            identity = char.get('identity')
            if identity:
                appearance = char.get('appearance', '')
                character_parts.append(f"{identity}，{appearance}" if appearance else identity)
            else:
                name = char.get('name', '未知')
                age_group = char.get('age_group', '未知')
                appearance = char.get('appearance', '')
                character_parts.append(f"{name}（{age_group}），{appearance}")
        characters_str = "\n".join([f"- {c}" for c in character_parts])

    # 获取场景信息
    scene_atmosphere = ""
    if hasattr(shot, 'scene') and shot.scene:
        scene_atmosphere = shot.scene.atmosphere or ""

    # 获取分镜时长
    shot_duration = shot.video_duration if hasattr(shot, 'video_duration') and shot.video_duration else 5

    if paradigm == "video_only":
        user_prompt = f"""请根据以下数据，按照“无声电影感视觉范式”为 AI 视频生成器生成提示词：

### 1. 核心分镜数据
- **画面描述**：{script}
- **图片提示词（关键参考）**：{image_prompt if image_prompt else '无'}
- **氛围基调**：{scene_atmosphere if scene_atmosphere else '未指定'}
- **视频时长**：{shot_duration} 秒

### 2. 登场角色
{characters_str if characters_str else '（本分镜无特定角色）'}

---
**生成要求**：
1. **彻底静音**：严禁出现任何台词、声音描述或声音角色。
2. **纯视觉 Actions**：将总时长 {shot_duration} 秒拆解为动作节拍。必须包含：镜头移动、谁在做动作、动作细节、神态表情。
3. **视觉风格**：电影质感动画风格。
4. **Cinematography**：设计精妙的运镜和光影，通过视觉传达情绪。"""
    else:
        # 针对 video_generation_v2 模板优化的输入格式
        user_prompt = f"""请根据以下分镜数据，生成详细的视频提示词：

图片提示词：{image_prompt if image_prompt else '无'}
分镜剧本：{script}
台词/旁白：{dialogues_str if dialogues_str else '（本分镜无台词）'}
角色信息：{characters_str if characters_str else '（本分镜无特定角色）'}
分镜时长：{shot_duration}秒

---
**其他参考信息**：
- 氛围基调：{scene_atmosphere if scene_atmosphere else '未指定'}"""

    # 调用 LLM
    try:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        
        logger.info(f"[{paradigm}] AI INPUT PROMPT...")
        response = ai_client.chat_completion(messages=messages, model=llm_model)
        video_prompt = response.get("content", "").strip()

        if not video_prompt:
            raise Exception("LLM 返回了空的视频提示词")

        logger.info(f"[{paradigm}] AI OUTPUT PROMPT:\n{video_prompt}")
        return video_prompt

    except Exception as e:
        logger.error(f"Error generating {paradigm} prompt: {str(e)}")
        raise Exception(f"视频提示词生成失败：{str(e)}")
