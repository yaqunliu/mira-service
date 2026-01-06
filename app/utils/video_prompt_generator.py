"""
视频提示词生成工具
从 VideoGenerationPipeline 中提取出来的独立函数
"""
import json
from typing import List, Dict
from app.core.logger import logger
from app.services.llm_service import LLMService


def generate_video_prompt(
    llm_model: str,
    shot,
    script: str,
    dialogues: List[Dict[str, str]],
    characters: List[Dict[str, str]] = None
) -> str:
    """
    使用 LLM 生成视频运动提示词

    Args:
        llm_model: LLM模型名称
        shot: Shot对象
        script: 分镜描述
        dialogues: 台词列表
        characters: 角色列表

    Returns:
        video_prompt: 视频运动提示词
    """
    # 构建系统提示词
    system_prompt = """你是一个专业的视频运镜设计师。根据分镜的画面描述和图片内容，生成适合的视频运动提示词。

视频提示词应该描述：
1. 画面中的运动元素（角色动作、物体移动）
2. 镜头运动（推拉摇移、跟随、环绕）
3. 环境变化（光影、天气、氛围）

要求：
- 提示词应该简洁明确，长度控制在 50-100 字
- 重点描述运动和变化，不要重复静态内容
- 符合分镜的氛围和节奏

返回格式：
{
  "video_prompt": "具体的视频运动提示词",
  "camera_movement": "镜头运动类型",
  "motion_intensity": "运动强度（low/medium/high）"
}
"""

    # 构建用户提示词
    narration_text = shot.narration if isinstance(shot.narration, str) else ""
    dialogue_text = shot.dialogue if shot.dialogue else ""

    # 格式化台词
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

    user_prompt = f"""请为以下分镜生成视频提示词：

分镜信息：
- 画面描述：{script}
- 旁白：{narration_text}
- 台词：{dialogue_text}
- 镜头类型：{shot.shot_type or '未指定'}
- 运镜方式：{shot.camera_movement or '未指定'}

场景氛围：{scene_atmosphere}

角色信息：
{characters_str if characters_str else '无'}

台词/旁白：
{dialogues_str if dialogues_str else '无'}

请生成适合的视频运动提示词。"""

    # 调用 LLM
    try:
        llm_service = LLMService(model_name=llm_model or 'gpt-4')
        response = llm_service.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format="json"
        )

        # 解析响应
        result = json.loads(response)
        video_prompt = result.get("video_prompt", "")

        logger.info(f"Generated video prompt: {video_prompt}")
        logger.info(f"Camera movement: {result.get('camera_movement', 'N/A')}")
        logger.info(f"Motion intensity: {result.get('motion_intensity', 'N/A')}")

        return video_prompt

    except json.JSONDecodeError as e:
        # 如果LLM没有返回正确的JSON，直接使用响应文本
        logger.warning(f"LLM response is not valid JSON, using raw text: {e}")
        return response.strip()
    except Exception as e:
        logger.error(f"Error calling LLM for video prompt generation: {str(e)}")
        # 降级策略：使用简单的提示词
        fallback_prompt = f"{shot.camera_movement or '平稳移动'}，{script[:50]}"
        logger.warning(f"Using fallback prompt: {fallback_prompt}")
        return fallback_prompt
