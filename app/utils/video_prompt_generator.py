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
    characters: List[Dict[str, str]] = None
) -> str:
    """
    使用 LLM 生成详细的视频提示词（纯文本，不是JSON）

    Args:
        llm_model: LLM模型名称
        shot: Shot对象
        script: 分镜描述
        dialogues: 台词列表
        characters: 角色列表

    Returns:
        video_prompt: 详细的中文视频提示词（纯文本）
    """
    # 构建系统提示词 - 基于 video_generation_v2.md
    system_prompt = """你是一个专业的视频运镜设计师。根据分镜的画面描述、角色信息和台词，生成详细的中文视频提示词。

## 输出格式
- **必须返回详细的中文提示词**，用于视频生成
- **必须包含以下所有要素**（按顺序描述）：
  1. **风格与镜头类型**：动画风格，动态镜头，景别（全景/中景/近景/特写），视角（平视/俯视/仰视），时长
  2. **剪辑结构**（重要！）：如果分镜时长较长（>6秒），建议拆分为多个小分镜
     - 例如：0-3秒 远景建立画面 -> cut切 -> 3-7秒 近景特写表情 -> dissolve溶解 -> 7-10秒 中景+横移
  3. **镜头运动**：推进/拉远/横移/旋转/固定/一镜到底，运动速度（缓慢/快速），镜头切换方式
  4. **场景环境**：地点，时间，天气，环境细节，氛围
  5. **光影效果**：光线类型，光影变化，色调，反射效果
  6. **角色描述**（如有多个角色需逐一描述）：
     - 角色标识（名字-年龄段）
     - 外观特征（服装、发型、配饰等）
     - 位置和姿态
     - 动作变化（起始→过程→结束）
     - 表情变化（起始→过程→结束）
     - 音色特征（如有对话）：性别、年龄、音调、语速、情绪
     - 说话内容（完整台词）
  7. **动态元素**：环境动态（雨滴、风、烟雾等），物体运动，粒子效果
  8. **细节强调**：面部表情细节，情绪传达，重点动作
  9. **技术要求**：画质要求，动画风格，帧率要求，音频同步要求

## 规则
- **输出必须是中文**
- **输出必须详细完整**，包含上述所有要素
- 风格固定为动画/动漫风格；禁止写实/真人风格
- **输出仅为一段详细的中文文本提示词**，不要使用JSON格式，不要添加额外解释
- **优先使用复杂剪辑**：分镜时长>6秒时，应拆分为多个小分镜（不同景别+运镜组合）
- 镜头运动描述要具体（例如："从全景缓慢推近到中景（约3秒），然后横移（约2秒）"）
- 剪辑切换要明确（例如："cut快切到近景"、"dissolve溶解过渡到远景"）
- 角色动作和表情变化要描述过程（例如："表情从紧张逐渐变得沮丧"）
- 如有对话，必须包含完整的音色特征和说话内容
"""

    # 格式化台词/旁白（从参数 dialogues 获取，已在调用方解析好）
    dialogues_str = ""
    if dialogues:
        dialogues_str = "\n".join([f"- {list(d.keys())[0]}: {list(d.values())[0]}" for d in dialogues])

    # 格式化角色信息
    characters_str = ""
    if characters:
        character_parts = []
        for char in characters:
            # 优先使用智能角色标识（包含状态信息）
            identity = char.get('identity')
            if identity:
                # 使用角色标识（如：张三-青年-雨天湿透）
                appearance = char.get('appearance', '')
                character_parts.append(f"{identity}，{appearance}" if appearance else identity)
            else:
                # 兼容旧格式
                name = char.get('name', '未知')
                age_group = char.get('age_group', '未知')
                appearance = char.get('appearance', '')
                character_parts.append(f"{name}（{age_group}），{appearance}")
        characters_str = "\n".join([f"- {c}" for c in character_parts])

    # 获取场景信息
    scene_atmosphere = ""
    if hasattr(shot, 'scene') and shot.scene:
        scene_atmosphere = shot.scene.atmosphere or ""

    # 获取分镜时长（用于指导剪辑结构）
    shot_duration = shot.video_duration if hasattr(shot, 'video_duration') and shot.video_duration else 5

    user_prompt = f"""请为以下分镜生成详细的视频提示词：

分镜信息：
- 画面描述：{script}
- 场景氛围：{scene_atmosphere}
- 分镜时长：{shot_duration}秒

角色信息：
{characters_str if characters_str else '无'}

台词/旁白：
{dialogues_str if dialogues_str else '无'}

请按照要求生成一段详细完整的中文视频提示词。"""

    # 调用 LLM
    try:
        ai_client = AIClient(llm_model_name=llm_model)

        # 构建消息
        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ]

        # 调用 AI（不使用 JSON 格式）
        response = ai_client.chat_completion(
            messages=messages,
            model=llm_model
        )

        video_prompt = response.get("content", "").strip()

        if not video_prompt:
            raise Exception("LLM 返回了空的视频提示词")

        logger.info(f"Generated video prompt ({len(video_prompt)} chars): {video_prompt[:200]}...")

        return video_prompt

    except Exception as e:
        logger.error(f"Error calling LLM for video prompt generation: {str(e)}")
        raise Exception(f"视频提示词生成失败：{str(e)}")
