"""
视频提示词生成工具
从 VideoGenerationPipeline 中提取出来的独立函数

V6 版本：三维度专业版（画面+背景音+台词）
"""
import json
from typing import List, Dict, Optional
from app.core.logger import logger
from app.utils.ai_client import AIClient


def generate_video_prompt(
    llm_model: str,
    shot,
    script: str,
    dialogues: List[Dict[str, str]],
    characters: List[Dict[str, str]] = None,
    image_prompt: str = None,
    start_frame_prompt: str = None,
    end_frame_prompt: str = None
) -> Dict[str, str]:
    """
    使用 LLM 生成详细的视频提示词（V6：三维度专业版 - 画面+背景音+台词）
    
    Args:
        llm_model: LLM 模型名称
        shot: 分镜对象
        script: 分镜剧本
        dialogues: 台词列表
        characters: 角色信息列表
        image_prompt: 图片提示词（兼容旧版，等同于 start_frame_prompt）
        start_frame_prompt: 首帧图片提示词（V5新增）
        end_frame_prompt: 尾帧图片提示词（V5新增）
    
    Returns:
        Dict: {"video_prompt": str, "cut_method": str, "cut_reason": str}
    """
    # 兼容旧版：如果没有传 start_frame_prompt，使用 image_prompt
    if not start_frame_prompt and image_prompt:
        start_frame_prompt = image_prompt
    
    return _generate_video_prompt_internal(
        llm_model=llm_model,
        shot=shot,
        script=script,
        dialogues=dialogues,
        characters=characters,
        start_frame_prompt=start_frame_prompt,
        end_frame_prompt=end_frame_prompt,
        paradigm="standard"
    )


def generate_video_only_prompt(
    llm_model: str,
    shot,
    script: str,
    characters: List[Dict[str, str]] = None,
    image_prompt: str = None,
    start_frame_prompt: str = None,
    end_frame_prompt: str = None
) -> Dict[str, str]:
    """
    生成纯视频提示词（无声、无台词，专注于运镜和动作）
    """
    # 兼容旧版
    if not start_frame_prompt and image_prompt:
        start_frame_prompt = image_prompt
    
    return _generate_video_prompt_internal(
        llm_model=llm_model,
        shot=shot,
        script=script,
        dialogues=[],  # 强制无台词
        characters=characters,
        start_frame_prompt=start_frame_prompt,
        end_frame_prompt=end_frame_prompt,
        paradigm="video_only"
    )


def _generate_video_prompt_internal(
    llm_model: str,
    shot,
    script: str,
    dialogues: List[Dict[str, str]],
    characters: List[Dict[str, str]] = None,
    start_frame_prompt: str = None,
    end_frame_prompt: str = None,
    paradigm: str = "standard"
) -> Dict[str, str]:
    """
    内部统一生成函数（V6版本 - 三维度专业版）
    
    Returns:
        Dict: {"video_prompt": str, "cut_method": str, "cut_reason": str}
    """
    # 初始化 AIClient
    ai_client = AIClient(llm_model_name=llm_model)

    # 加载提示词模板（V6 - 三维度专业版）
    try:
        template_version = "video_generation_v6"
        full_template = ai_client._load_prompt_template(template_version)
        logger.info(f"成功加载视频提示词模板 {template_version}")

        # V6 模板结构：整个模板作为系统提示词，输入数据通过变量替换
        system_prompt = full_template

        # 如果是 video_only 模式，在系统提示词后面添加额外指令
        if paradigm == "video_only":
            system_prompt += "\n\n**重要：当前为纯视频模式，请忽略所有台词和声音描述，背景音维度仅保留环境音层，人物对白维度全部标注（无）。在生成的 video_prompt 中不要包含任何语音或对话相关的描述。**"

    except Exception as e:
        logger.error(f"加载视频提示词模板 {template_version} 失败: {e}")
        raise Exception(f"视频提示词模板加载失败，请检查 {template_version}.md 是否存在: {str(e)}")

    # 格式化台词数据
    dialogues_str = ""
    if paradigm != "video_only" and dialogues:
        dialogues_str = "\n".join([f"- {list(d.keys())[0]}: {list(d.values())[0]}" for d in dialogues])
    else:
        dialogues_str = "（本分镜无台词）"

    # 格式化角色数据
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

    # V5：替换模板中的变量
    prompt = system_prompt
    prompt = prompt.replace("{{SHOT_STORY}}", script if script else "无")
    prompt = prompt.replace("{{START_FRAME_PROMPT}}", start_frame_prompt if start_frame_prompt else "无")
    prompt = prompt.replace("{{END_FRAME_PROMPT}}", end_frame_prompt if end_frame_prompt else "无")
    prompt = prompt.replace("{{CHARACTERS}}", characters_str)
    prompt = prompt.replace("{{DIALOGUES}}", dialogues_str)
    prompt = prompt.replace("{{DURATION}}", str(shot_duration))

    # 如果有氛围基调，附加信息
    scene_atmosphere = ""
    if paradigm != "video_only" and hasattr(shot, 'scene') and shot.scene:
        scene_atmosphere = shot.scene.atmosphere or ""
    if scene_atmosphere:
        prompt += f"\n\n**补充信息 - 氛围基调**：{scene_atmosphere}"
    
    # 调用 LLM
    try:
        messages = [
            {"role": "system", "content": "你是一个专业的视频提示词生成专家，请严格按照模板要求输出JSON格式的结果。"},
            {"role": "user", "content": prompt}
        ]
        
        logger.info(f"[{paradigm}] AI INPUT PROMPT for V6...")
        response = ai_client.chat_completion(messages=messages, model=llm_model)
        response_content = response.get("content", "").strip()

        if not response_content:
            raise Exception("LLM 返回了空的响应")

        logger.info(f"[{paradigm}] AI OUTPUT:\n{response_content}")
        
        # 解析 JSON 响应
        result = _parse_video_prompt_response(response_content)
        
        return result

    except Exception as e:
        logger.error(f"Error generating {paradigm} prompt: {str(e)}")
        raise Exception(f"视频提示词生成失败：{str(e)}")


def _parse_video_prompt_response(response_content: str) -> Dict[str, str]:
    """
    解析 LLM 返回的 JSON 响应
    
    Args:
        response_content: LLM 返回的原始内容
        
    Returns:
        Dict: {"video_prompt": str, "cut_method": str, "cut_reason": str}
    """
    # 尝试提取 JSON 块
    json_content = response_content
    
    # 如果包含 markdown 代码块，提取其中的内容
    if "```json" in response_content:
        start = response_content.find("```json") + 7
        end = response_content.find("```", start)
        if end > start:
            json_content = response_content[start:end].strip()
    elif "```" in response_content:
        start = response_content.find("```") + 3
        end = response_content.find("```", start)
        if end > start:
            json_content = response_content[start:end].strip()
    
    try:
        result = json.loads(json_content)
        
        # 验证必要字段
        video_prompt = result.get("video_prompt", "")
        cut_method = result.get("cut_method", "smooth_transition")
        cut_reason = result.get("cut_reason", "")
        
        if not video_prompt:
            raise ValueError("video_prompt 字段为空")
        
        return {
            "video_prompt": video_prompt,
            "cut_method": cut_method,
            "cut_reason": cut_reason
        }
        
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析失败，尝试作为纯文本处理: {e}")
        # 降级处理：如果不是有效的 JSON，将整个响应作为 video_prompt
        return {
            "video_prompt": response_content,
            "cut_method": "smooth_transition",
            "cut_reason": "默认转场方式（JSON解析失败）"
        }
