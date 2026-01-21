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
        # 默认使用 V3 模板，后续可配置为 V4
        # 根据需求切换到 V4 模板
        template_version = "video_generation_v4"
        full_template = ai_client._load_prompt_template(template_version)
        logger.info(f"成功加载视频提示词模板 {template_version}")
        
        # 将模板拆分为系统提示词和用户提示词模板
        if "## 待生成数据输入" in full_template:
            parts = full_template.split("## 待生成数据输入")
            system_prompt = parts[0].strip()
            user_prompt_template = parts[1].strip()
        else:
            system_prompt = full_template
            user_prompt_template = """请根据以下数据生成 V4 格式的视频提示词：
- **图片提示词**：{{IMAGE_PROMPT}}
- **分镜剧本**：{{SCRIPT}}
- **台词/旁白**：{{DIALOGUES}}
- **角色信息**：{{CHARACTERS}}
- **分镜时长**：{{DURATION}}秒"""

        # 如果是 video_only 模式，在系统提示词后面添加额外指令
        if paradigm == "video_only":
            system_prompt += "\n\n**重要：当前为纯视频模式，请忽略所有台词和声音描述，不要在输出中包含任何音频相关的特征或内容。**"
            
    except Exception as e:
        logger.error(f"加载视频提示词模板 {template_version} 失败: {e}")
        raise Exception(f"视频提示词模板加载失败，请检查 {template_version}.md 是否存在: {str(e)}")

    # 格式化数据
    dialogues_str = ""
    if paradigm != "video_only" and dialogues:
        dialogues_str = "\n".join([f"- {list(d.keys())[0]}: {list(d.values())[0]}" for d in dialogues])
    else:
        dialogues_str = "（本分镜无台词）"

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
    else:
        characters_str = "（本分镜无特定角色）"

    # 获取分镜时长
    shot_duration = shot.video_duration if hasattr(shot, 'video_duration') and shot.video_duration else 5

    # 填充用户提示词模板
    user_prompt = user_prompt_template.replace("{{IMAGE_PROMPT}}", image_prompt if image_prompt else '无')
    user_prompt = user_prompt.replace("{{SCRIPT}}", script)
    user_prompt = user_prompt.replace("{{DIALOGUES}}", dialogues_str)
    user_prompt = user_prompt.replace("{{CHARACTERS}}", characters_str)
    user_prompt = user_prompt.replace("{{DURATION}}", str(shot_duration))

    # 如果有氛围基调，附加到用户提示词末尾
    if not paradigm == "video_only":
        scene_atmosphere = ""
        if hasattr(shot, 'scene') and shot.scene:
            scene_atmosphere = shot.scene.atmosphere or ""
        if scene_atmosphere:
            user_prompt += f"\n- **氛围基调**：{scene_atmosphere}"
    
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
