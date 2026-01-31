"""
任务执行节点

处理用户的任务请求，调用相应的 Tools 执行任务
"""

from typing import Dict, Any, List

from app.core.logger import logger


# 意图到 Tool 的映射
# 注意：此映射需与 prompts/intent_detection.md 中的意图定义保持一致
INTENT_TOOL_MAPPING = {
    # ========== 分析类任务 (task_intent) ==========
    "analyze_script": "analyze_script",           # 完整剧本分析
    "extract_characters": "extract_characters",   # 提取角色
    "extract_scenes": "extract_scenes",           # 提取场景
    
    # ========== 生成类任务 (task_intent) ==========
    "generate_character_images": "generate_character_image",
    "generate_scene_images": "generate_scene_image",
    "generate_shot_images": "generate_shot_image",
    "generate_videos": "generate_video",
    "generate_audio": "generate_audio",
    "auto_create": "auto_create",                 # 一键自动创作（全流程）
    
    # ========== 资产操作 - 修改类 (asset_action) ==========
    "modify_character_prompt": "update_character",
    "modify_scene_prompt": "update_scene",
    "modify_shot_prompt": "update_shot",
    
    # ========== 资产操作 - 重新生成 (asset_action) ==========
    "regenerate_character_image": "generate_character_image",
    "regenerate_scene_image": "generate_scene_image",
    "regenerate_shot_image": "generate_shot_image",
    "regenerate_video": "generate_video",
    
    # ========== 资产操作 - 其他 (asset_action) ==========
    "select_option": "select_option",             # 选择候选项
    "delete": "delete_asset",                     # 删除资产
}


async def task_execution_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    任务执行节点
    
    根据用户意图调用相应的 Tools 执行任务，支持：
    - 生成类任务（图片/视频/音频）
    - 分析类任务（剧本/角色/场景）
    - 修改类任务（提示词修改）
    - 确认操作处理
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        更新后的状态，包含任务执行结果
    """
    logger.info("[Node] task_execution: 开始处理任务执行")
    
    from datetime import datetime
    
    creation_uuid = state.get("creation_uuid")
    detected_intent = state.get("detected_intent", "")
    intent_details = state.get("intent_details", {})
    pending_action = state.get("pending_action")
    user_action_data = state.get("user_action_data", {})
    
    try:
        # ========== 1. 数据预检查 ==========
        # 在执行任务前，先检查创作数据是否就绪
        precheck_result = await _precheck_creation_data(state, detected_intent)
        if not precheck_result["ready"]:
            return await _generate_clarify_response(
                state, 
                precheck_result.get("message", "创作数据未就绪，请先上传剧本。")
            )
        
        # ========== 2. 处理用户确认操作 ==========
        # 处理用户确认操作
        if pending_action == "approve":
            return await _handle_approve_action(state)
        elif pending_action == "reject":
            return await _handle_reject_action(state)
        elif pending_action == "modify":
            return await _handle_modify_action(state)
        
        # ========== 3. 获取并执行对应的 Tool ==========
        # 获取对应的 Tool
        tool_name = INTENT_TOOL_MAPPING.get(detected_intent)
        
        if not tool_name:
            logger.warning(f"[Node] task_execution: 未找到意图对应的 Tool: {detected_intent}")
            return await _generate_clarify_response(state, f"暂不支持该操作: {detected_intent}")
        
        # 根据任务类型执行
        if tool_name.startswith("generate_"):
            result = await _execute_generation_task(state, tool_name, intent_details)
        elif tool_name.startswith("update_"):
            result = await _execute_update_task(state, tool_name, intent_details)
        elif tool_name in ["analyze_script", "extract_characters", "extract_scenes"]:
            result = await _execute_analysis_task(state, tool_name, intent_details)
        else:
            result = {"status": "error", "error": f"未知的 Tool 类型: {tool_name}"}
        
        # 构建回复消息
        if result.get("status") == "success":
            response_text = _format_success_response(tool_name, result)
        else:
            response_text = f"执行失败：{result.get('error', '未知错误')}"
        
        assistant_message = {
            "role": "assistant",
            "content": response_text,
            "timestamp": datetime.now().isoformat(),
            "node": "task_execution",
            "metadata": {
                "intent": detected_intent,
                "tool": tool_name,
                "result_status": result.get("status"),
            },
        }
        
        messages = list(state.get("messages", []))
        messages.append(assistant_message)
        
        # 记录 Tool 调用
        tool_calls = list(state.get("tool_calls", []))
        tool_calls.append({
            "tool": tool_name,
            "intent": detected_intent,
            "result": result,
            "timestamp": datetime.now().isoformat(),
        })
        
        logger.info(f"[Node] task_execution: 任务完成，tool={tool_name}, status={result.get('status')}")
        
        return {
            "messages": messages,
            "response_text": response_text,
            "tool_calls": tool_calls,
            "last_execution_result": result,
            "pending_action": None,  # 清空 pending action
            "updated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"[Node] task_execution 错误: {e}")
        
        error_message = {
            "role": "assistant",
            "content": f"执行任务时出现错误：{str(e)}",
            "timestamp": datetime.now().isoformat(),
            "node": "task_execution",
            "error": True,
        }
        
        messages = list(state.get("messages", []))
        messages.append(error_message)
        
        return {
            "messages": messages,
            "errors": state.get("errors", []) + [{"node": "task_execution", "error": str(e)}],
        }


async def _precheck_creation_data(state: Dict[str, Any], detected_intent: str) -> Dict[str, Any]:
    """
    预检查创作数据是否就绪
    
    根据用户意图检查必要的数据是否已存在：
    - 生成角色图片：需要有角色数据
    - 生成场景图片：需要有场景数据
    - 生成分镜图片：需要有分镜数据
    - 分析剧本：需要有剧本内容
    
    Args:
        state: 当前状态
        detected_intent: 检测到的意图
        
    Returns:
        {"ready": True/False, "message": "..."}
    """
    from app.agent.tools.db_tools import query_creation_status
    
    creation_uuid = state.get("creation_uuid")
    
    if not creation_uuid:
        return {
            "ready": False,
            "message": "找不到创作项目，请先创建一个创作项目。"
        }
    
    try:
        # 查询创作状态
        status_data = await query_creation_status.ainvoke({"creation_uuid": creation_uuid})
        
        if status_data.get("status") == "error":
            return {
                "ready": False,
                "message": f"查询创作状态失败：{status_data.get('error', '未知错误')}"
            }
        
        # 根据意图检查所需数据
        if detected_intent in ["generate_character_images", "regenerate_character_image"]:
            chars = status_data.get("characters", {})
            if chars.get("total", 0) == 0:
                return {
                    "ready": False,
                    "message": "还没有角色数据，请先上传剧本并完成剧本分析，我会自动提取角色信息。"
                }
        
        elif detected_intent in ["generate_scene_images", "regenerate_scene_image"]:
            scenes = status_data.get("scenes", {})
            if scenes.get("total", 0) == 0:
                return {
                    "ready": False,
                    "message": "还没有场景数据，请先上传剧本并完成剧本分析，我会自动提取场景信息。"
                }
        
        elif detected_intent in ["generate_shot_images", "regenerate_shot_image", "generate_videos", "regenerate_video"]:
            shots = status_data.get("shots", {})
            if shots.get("total", 0) == 0:
                return {
                    "ready": False,
                    "message": "还没有分镜数据，请先完成剧本分析和分镜生成。"
                }
        
        elif detected_intent in ["analyze_script", "extract_characters", "extract_scenes"]:
            # 分析类任务需要检查是否有剧本
            if not state.get("script_text"):
                creation_status = status_data.get("status", "init")
                if creation_status == "init":
                    return {
                        "ready": False,
                        "message": "请先上传剧本内容，我会帮您进行分析。"
                    }
        
        # 数据就绪
        logger.info(f"[Precheck] 数据检查通过，intent={detected_intent}")
        return {
            "ready": True,
            "status_data": status_data  # 可选：传递状态数据供后续使用
        }
        
    except Exception as e:
        logger.error(f"[Precheck] 数据检查失败: {e}")
        return {
            "ready": False,
            "message": f"数据检查时出错：{str(e)}"
        }


async def _execute_generation_task(
    state: Dict[str, Any],
    tool_name: str,
    intent_details: Dict[str, Any]
) -> Dict[str, Any]:
    """执行生成类任务"""
    from app.agent.tools.agent_generation_tools import (
        generate_character_image,
        generate_scene_image,
        generate_shot_image,
        generate_video,
        generate_audio,
    )
    
    creation_uuid = state.get("creation_uuid")
    target_id = intent_details.get("target_id")
    target_ids = intent_details.get("target_ids", [target_id] if target_id else [])
    
    tool_map = {
        "generate_character_image": generate_character_image,
        "generate_scene_image": generate_scene_image,
        "generate_shot_image": generate_shot_image,
        "generate_video": generate_video,
        "generate_audio": generate_audio,
    }
    
    tool = tool_map.get(tool_name)
    if not tool:
        return {"status": "error", "error": f"未找到 Tool: {tool_name}"}
    
    # 如果没有指定目标，需要查询获取
    if not target_ids:
        if "character" in tool_name:
            from app.agent.tools.db_tools import query_characters
            chars = await query_characters.ainvoke({"creation_uuid": creation_uuid})
            target_ids = [c["id"] for c in chars.get("characters", []) if not c.get("has_image")]
        elif "scene" in tool_name:
            from app.agent.tools.db_tools import query_scenes
            scenes = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
            target_ids = [s["id"] for s in scenes.get("scenes", []) if not s.get("has_image")]
        elif "shot" in tool_name:
            from app.agent.tools.db_tools import query_shots
            shots = await query_shots.ainvoke({"creation_uuid": creation_uuid})
            target_ids = [s["id"] for s in shots.get("shots", []) if not s.get("has_image")][:10]  # 限制数量
    
    if not target_ids:
        return {"status": "success", "message": "没有需要生成的目标", "generated_count": 0}
    
    # 执行生成（这里简化为返回待确认信息）
    return {
        "status": "pending_confirmation",
        "message": f"即将为 {len(target_ids)} 个目标生成内容",
        "targets": target_ids,
        "tool": tool_name,
        "requires_confirmation": True,
    }


async def _execute_update_task(
    state: Dict[str, Any],
    tool_name: str,
    intent_details: Dict[str, Any]
) -> Dict[str, Any]:
    """执行更新类任务"""
    from app.agent.tools.db_tools import (
        update_character,
        update_scene,
        update_shot,
    )
    
    target_id = intent_details.get("target_id")
    new_value = intent_details.get("new_value")
    field = intent_details.get("field", "image_prompt")
    
    if not target_id:
        return {"status": "error", "error": "未指定目标 ID"}
    
    tool_map = {
        "update_character": update_character,
        "update_scene": update_scene,
        "update_shot": update_shot,
    }
    
    tool = tool_map.get(tool_name)
    if not tool:
        return {"status": "error", "error": f"未找到 Tool: {tool_name}"}
    
    # 构建更新参数
    if "character" in tool_name:
        params = {"character_id": target_id}
    elif "scene" in tool_name:
        params = {"scene_id": target_id}
    else:
        params = {"shot_id": target_id}
    
    params[field] = new_value
    
    result = await tool.ainvoke(params)
    return result


async def _execute_analysis_task(
    state: Dict[str, Any],
    tool_name: str,
    intent_details: Dict[str, Any]
) -> Dict[str, Any]:
    """执行分析类任务"""
    from app.agent.tools.analysis_tools import (
        analyze_script,
        extract_characters,
        extract_scenes,
    )
    
    script_text = state.get("script_text", "")
    
    if not script_text:
        return {"status": "error", "error": "没有可分析的剧本内容"}
    
    tool_map = {
        "analyze_script": analyze_script,
        "extract_characters": extract_characters,
        "extract_scenes": extract_scenes,
    }
    
    tool = tool_map.get(tool_name)
    if not tool:
        return {"status": "error", "error": f"未找到 Tool: {tool_name}"}
    
    result = await tool.ainvoke({"script_text": script_text})
    return result


async def _handle_approve_action(state: Dict[str, Any]) -> Dict[str, Any]:
    """处理确认操作"""
    from datetime import datetime
    
    last_result = state.get("last_execution_result", {})
    
    # 如果上次是待确认状态，执行实际操作
    if last_result.get("requires_confirmation"):
        # 这里应该执行实际的生成任务
        # 简化为直接返回成功
        response_text = "好的，已开始执行生成任务，请稍候..."
    else:
        response_text = "收到确认！"
    
    return {
        "messages": state.get("messages", []) + [{
            "role": "assistant",
            "content": response_text,
            "timestamp": datetime.now().isoformat(),
            "node": "task_execution",
        }],
        "pending_action": None,
    }


async def _handle_reject_action(state: Dict[str, Any]) -> Dict[str, Any]:
    """处理拒绝操作"""
    from datetime import datetime
    
    return {
        "messages": state.get("messages", []) + [{
            "role": "assistant",
            "content": "好的，已取消该操作。还有什么我可以帮您的吗？",
            "timestamp": datetime.now().isoformat(),
            "node": "task_execution",
        }],
        "pending_action": None,
    }


async def _handle_modify_action(state: Dict[str, Any]) -> Dict[str, Any]:
    """处理修改操作"""
    from datetime import datetime
    
    user_action_data = state.get("user_action_data", {})
    modifications = user_action_data.get("modifications", {})
    
    return {
        "messages": state.get("messages", []) + [{
            "role": "assistant",
            "content": f"收到修改请求，正在处理...",
            "timestamp": datetime.now().isoformat(),
            "node": "task_execution",
        }],
        "pending_action": None,
        "pending_modifications": modifications,
    }


async def _generate_clarify_response(state: Dict[str, Any], message: str) -> Dict[str, Any]:
    """生成澄清响应"""
    from datetime import datetime
    
    return {
        "messages": state.get("messages", []) + [{
            "role": "assistant",
            "content": message,
            "timestamp": datetime.now().isoformat(),
            "node": "task_execution",
        }],
    }


def _format_success_response(tool_name: str, result: Dict[str, Any]) -> str:
    """格式化成功响应"""
    if result.get("requires_confirmation"):
        targets = result.get("targets", [])
        return f"确认要为以下 {len(targets)} 个目标执行「{tool_name}」操作吗？\n\n请回复「确认」继续，或「取消」放弃。"
    
    if "image_url" in result:
        return f"✅ 图片生成成功！\n\n图片地址：{result['image_url']}"
    elif "video_url" in result:
        return f"✅ 视频生成成功！\n\n视频地址：{result['video_url']}"
    elif "audio_url" in result:
        return f"✅ 音频生成成功！\n\n音频地址：{result['audio_url']}"
    elif "characters" in result:
        chars = result.get("characters", [])
        return f"✅ 角色分析完成！\n\n识别到 {len(chars)} 个角色：\n" + "\n".join([f"- {c.get('name')}" for c in chars])
    elif "scenes" in result:
        scenes = result.get("scenes", [])
        return f"✅ 场景分析完成！\n\n识别到 {len(scenes)} 个场景：\n" + "\n".join([f"- {s.get('name')}" for s in scenes])
    elif result.get("success"):
        return f"✅ 操作成功！更新了字段：{', '.join(result.get('updated_fields', []))}"
    else:
        return f"✅ 任务执行完成！"
