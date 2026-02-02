"""
查询节点 - ReAct Agent 模式

整合状态查询和知识问答，LLM 自主决定是否调用工具
"""

from typing import Dict, Any, List
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from app.core.logger import logger
from app.core.config import settings


# 系统提示词
QUERY_AGENT_SYSTEM_PROMPT = """你是漫剧创作助手，负责回答用户的查询问题。

## 你的能力

1. **创作进度查询**：可以查询角色、场景、分镜的生成状态
2. **漫剧知识问答**：可以回答构图、镜头语言、提示词技巧等专业问题
3. **一般问答**：对于简单问题可以直接回答

## 工具使用指南

- 用户问创作进度 → 调用 query_creation_status, query_characters, query_scenes, query_shots
- 用户问漫剧知识 → 调用 query_knowledge_base
- 用户问提示词技巧 → 调用 get_prompt_enhancement_suggestions
- 简单问题 → 直接回答，不需要调用工具

## 当前创作信息

创作 UUID: {creation_uuid}

## 回复要求

- 用友好的中文回答
- 查询结果用清晰的格式展示
- 如果查询不到数据，给出合理的解释
"""


def _get_query_tools() -> List:
    """获取查询相关的工具"""
    from app.agent.tools.db_tools import (
        query_creation_status,
        query_characters,
        query_scenes,
        query_shots,
    )
    from app.agent.tools.knowledge_tools import (
        query_knowledge_base,
        get_prompt_enhancement_suggestions,
        get_camera_angle_suggestions,
    )
    
    return [
        query_creation_status,
        query_characters,
        query_scenes,
        query_shots,
        query_knowledge_base,
        get_prompt_enhancement_suggestions,
        get_camera_angle_suggestions,
    ]


async def status_query_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    查询节点 - ReAct Agent 模式
    
    整合状态查询和知识问答，LLM 自主决定是否调用工具。
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        更新后的状态
    """
    logger.info("[Node] status_query: 开始处理查询（ReAct Agent 模式）")
    
    creation_uuid = state.get("creation_uuid")
    user_message = state.get("user_message", "")
    
    try:
        # 1. 准备工具
        tools = _get_query_tools()
        
        # 2. 创建带工具的 LLM
        llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3,
        )
        llm_with_tools = llm.bind_tools(tools)
        
        # 3. 构建消息
        system_prompt = QUERY_AGENT_SYSTEM_PROMPT.format(
            creation_uuid=creation_uuid or "未指定"
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        
        # 4. ReAct 循环（最多 3 轮工具调用）
        max_iterations = 3
        iteration = 0
        final_response = ""
        
        while iteration < max_iterations:
            iteration += 1
            logger.info(f"[Node] status_query: ReAct 循环 {iteration}/{max_iterations}")
            
            # 调用 LLM
            response = await llm_with_tools.ainvoke(messages)
            messages.append(response)
            
            # 检查是否有工具调用
            if not response.tool_calls:
                # 没有工具调用，LLM 直接回答
                final_response = response.content
                logger.info("[Node] status_query: LLM 直接回答，无工具调用")
                break
            
            # 执行工具调用
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]
                
                logger.info(f"[Node] status_query: 调用工具 {tool_name}, args={tool_args}")
                
                # 查找并执行工具
                tool_result = await _execute_tool(tools, tool_name, tool_args)
                
                # 添加工具结果到消息
                messages.append(ToolMessage(
                    content=str(tool_result),
                    tool_call_id=tool_id,
                ))
        
        # 如果循环结束还没有最终回复，再调用一次 LLM 生成总结
        if not final_response:
            logger.info("[Node] status_query: 生成最终总结")
            final_llm = ChatOpenAI(
                model=settings.LLM_MODEL_DEFAULT,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                temperature=0.7,
            )
            summary_response = await final_llm.ainvoke(messages)
            final_response = summary_response.content
        
        # 5. 构建返回结果
        assistant_message = {
            "role": "assistant",
            "content": final_response,
            "timestamp": datetime.now().isoformat(),
            "node": "status_query",
            "metadata": {
                "mode": "react_agent",
                "iterations": iteration,
            },
        }
        
        state_messages = list(state.get("messages", []))
        state_messages.append(assistant_message)
        
        logger.info(f"[Node] status_query: 查询完成，迭代次数={iteration}")
        
        return {
            "messages": state_messages,
            "response_text": final_response,
            "updated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"[Node] status_query 错误: {e}")
        
        error_message = {
            "role": "assistant",
            "content": f"抱歉，处理您的问题时出现错误：{str(e)}",
            "timestamp": datetime.now().isoformat(),
            "node": "status_query",
            "error": True,
        }
        
        state_messages = list(state.get("messages", []))
        state_messages.append(error_message)
        
        return {
            "messages": state_messages,
            "response_text": f"抱歉，处理您的问题时出现错误：{str(e)}",
            "errors": state.get("errors", []) + [{"node": "status_query", "error": str(e)}],
        }


async def _execute_tool(tools: List, tool_name: str, tool_args: Dict[str, Any]) -> Any:
    """执行指定的工具"""
    for tool in tools:
        if tool.name == tool_name:
            try:
                result = await tool.ainvoke(tool_args)
                return result
            except Exception as e:
                logger.error(f"[Node] status_query: 工具 {tool_name} 执行失败: {e}")
                return {"error": str(e)}
    
    return {"error": f"未找到工具: {tool_name}"}
