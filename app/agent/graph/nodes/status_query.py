"""
状态查询节点

处理用户的状态查询请求，返回创作进度信息
"""

from typing import Dict, Any

from app.core.logger import logger


async def status_query_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    状态查询节点
    
    根据用户意图查询创作状态，支持：
    - 整体进度查询
    - 特定资产（角色/场景/分镜）状态查询
    - 当前阶段详情查询
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        更新后的状态，包含状态查询结果和回复消息
    """
    logger.info("[Node] status_query: 开始处理状态查询")
    
    from datetime import datetime
    from app.agent.prompts import load_and_format
    from app.agent.tools.db_tools import query_creation_status
    
    creation_uuid = state.get("creation_uuid")
    detected_intent = state.get("detected_intent", "overall_status")
    intent_details = state.get("intent_details", {})
    
    try:
        # 查询创作状态
        status_data = await query_creation_status.ainvoke({
            "creation_uuid": creation_uuid
        })
        
        # 根据具体意图返回不同详细程度的信息
        if detected_intent == "overall_status":
            # 整体进度
            response_context = {
                "status_type": "overall",
                "creation_status": status_data,
                "current_stage": state.get("current_stage", "init"),
            }
        elif detected_intent == "character_status":
            # 角色状态
            from app.agent.tools.db_tools import query_characters
            characters_data = await query_characters.ainvoke({
                "creation_uuid": creation_uuid,
                "include_images": True,
            })
            response_context = {
                "status_type": "characters",
                "characters": characters_data,
                "summary": status_data.get("characters", {}),
            }
        elif detected_intent == "scene_status":
            # 场景状态
            from app.agent.tools.db_tools import query_scenes
            scenes_data = await query_scenes.ainvoke({
                "creation_uuid": creation_uuid,
                "include_images": True,
            })
            response_context = {
                "status_type": "scenes",
                "scenes": scenes_data,
                "summary": status_data.get("scenes", {}),
            }
        elif detected_intent == "shot_status":
            # 分镜状态
            from app.agent.tools.db_tools import query_shots
            shots_data = await query_shots.ainvoke({
                "creation_uuid": creation_uuid,
                "include_details": False,
            })
            response_context = {
                "status_type": "shots",
                "shots": shots_data,
                "summary": status_data.get("shots", {}),
            }
        else:
            response_context = {
                "status_type": "overall",
                "creation_status": status_data,
            }
        
        # 使用提示词生成回复
        prompt = load_and_format("status_response", response_context)
        
        from langchain_openai import ChatOpenAI
        from app.core.config import settings
        
        llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.7,
            streaming=True,
        )
        
        response = await llm.ainvoke(prompt)
        response_text = response.content
        
        # 构建助手消息
        assistant_message = {
            "role": "assistant",
            "content": response_text,
            "timestamp": datetime.now().isoformat(),
            "node": "status_query",
            "metadata": {
                "intent": detected_intent,
                "status_type": response_context.get("status_type"),
            },
        }
        
        # 更新消息历史
        messages = list(state.get("messages", []))
        messages.append(assistant_message)
        
        logger.info(f"[Node] status_query: 查询完成，intent={detected_intent}")
        
        return {
            "messages": messages,
            "response_text": response_text,
            "status_query_result": status_data,
            "updated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"[Node] status_query 错误: {e}")
        
        error_message = {
            "role": "assistant",
            "content": f"抱歉，查询状态时出现错误：{str(e)}",
            "timestamp": datetime.now().isoformat(),
            "node": "status_query",
            "error": True,
        }
        
        messages = list(state.get("messages", []))
        messages.append(error_message)
        
        return {
            "messages": messages,
            "errors": state.get("errors", []) + [{"node": "status_query", "error": str(e)}],
        }
