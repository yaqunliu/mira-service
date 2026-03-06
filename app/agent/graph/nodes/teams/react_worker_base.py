"""
ReAct Worker Base - Worker Node 基类

提供 ReAct 循环的基础实现，供各 Worker Node 继承使用。
"""

from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
from datetime import datetime

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from app.core.logger import logger
from app.core.config import settings
from app.agent.state.schemas import ComicDramaState


class ReActWorkerNode(ABC):
    """
    ReAct Worker Node 基类

    提供 ReAct 循环的通用实现，子类只需定义：
    - get_system_prompt(): 系统提示词
    - get_tools(): 可用工具列表
    - process_result(): 处理最终结果
    """

    # 是否使用 ReAct 模式（可被子类覆盖）
    USE_REACT = True
    
    def __init__(self, model: Optional[str] = None, temperature: float = 0.3):
        """初始化 LLM"""
        self.llm = ChatOpenAI(
            model=model or settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=temperature,
            timeout=120,
            max_retries=2,
        )
        self.node_name = self.__class__.__name__
    
    @abstractmethod
    def get_system_prompt(self, state: ComicDramaState) -> str:
        """获取系统提示词（子类实现）"""
        pass
    
    @abstractmethod
    def get_tools(self) -> List:
        """获取可用工具列表（子类实现）"""
        pass
    
    @abstractmethod
    async def process_result(self, state: ComicDramaState, final_response: str, tool_results: List[Dict]) -> Dict[str, Any]:
        """处理最终结果（子类实现）"""
        pass
    
    def get_user_message(self, state: ComicDramaState) -> str:
        """获取用户消息（可被子类覆盖）"""
        return state.get("user_message", "")
    
    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行 ReAct 循环
        
        Args:
            state: 当前 Graph 状态
            
        Returns:
            更新后的状态
        """
        import asyncio
        
        max_attempts = 3
        delay_seconds = 3.0
        
        for attempt in range(1, max_attempts + 1):
            try:
                return await self._run_impl(state)
            except Exception as e:
                if attempt < max_attempts:
                    logger.warning(f"[{self.node_name}] 第 {attempt} 次执行失败: {e}，{delay_seconds}秒后重试...")
                    await asyncio.sleep(delay_seconds)
                else:
                    logger.error(f"[{self.node_name}] 重试 {max_attempts} 次后仍失败: {e}")
                    raise
    
    async def _run_impl(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        ReAct 循环的实际实现
        """
        logger.info(f"[{self.node_name}] 开始执行 (ReAct={self.USE_REACT})")
        
        try:
            if not self.USE_REACT:
                # 非 ReAct 模式，直接调用子类的 legacy 处理
                return await self.run_legacy(state)
            
            # ReAct 模式
            tools = self.get_tools()
            llm_with_tools = self.llm.bind_tools(tools) if tools else self.llm
            
            # 构建消息
            system_prompt = self.get_system_prompt(state)
            user_message = self.get_user_message(state)
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_message),
            ]
            
            # ReAct 循环
            iteration = 0
            final_response = ""
            tool_results = []
            max_iterations = settings.LANGGRAPH_RECURSION_LIMIT

            while iteration < max_iterations:
                iteration += 1
                logger.info(f"[{self.node_name}] ReAct 循环 {iteration}/{max_iterations}")
                
                response = await llm_with_tools.ainvoke(messages)
                messages.append(response)
                
                # 检查是否有工具调用
                if not response.tool_calls:
                    final_response = response.content
                    logger.info(f"[{self.node_name}] LLM 直接回答，无工具调用")
                    logger.info(f"[{self.node_name}] 回答内容: {final_response[:200]}...")
                    break
                
                # 执行工具调用
                logger.info(f"[{self.node_name}] LLM 请求调用 {len(response.tool_calls)} 个工具")
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_id = tool_call["id"]
                    
                    # 自动解析 JSON 字符串参数
                    import json
                    for key, value in list(tool_args.items()):
                        if isinstance(value, str) and value.startswith('['):
                            try:
                                tool_args[key] = json.loads(value)
                                logger.info(f"[{self.node_name}] 解析参数 {key} 为 JSON 数组")
                            except:
                                pass
                    
                    logger.info(f"[{self.node_name}] 调用工具 {tool_name}")
                    logger.info(f"[{self.node_name}] 工具参数: {tool_args}")
                    
                    tool_result = await self._execute_tool(tools, tool_name, tool_args)
                    logger.info(f"[{self.node_name}] 工具 {tool_name} 执行完成")
                    logger.info(f"[{self.node_name}] 工具结果: {str(tool_result)[:200]}...")
                    
                    tool_results.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": tool_result,
                    })
                    
                    messages.append(ToolMessage(
                        content=str(tool_result),
                        tool_call_id=tool_id,
                    ))
            
            # 如果循环结束还没有最终回复
            if not final_response:
                logger.info(f"[{self.node_name}] 生成最终总结")
                final_llm = ChatOpenAI(
                    model=settings.LLM_MODEL_DEFAULT,
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL,
                    temperature=0.7,
                )
                summary_response = await final_llm.ainvoke(messages)
                final_response = summary_response.content
            
            # 处理结果
            result = await self.process_result(state, final_response, tool_results)
            
            # 添加元数据
            result["_react_metadata"] = {
                "node": self.node_name,
                "iterations": iteration,
                "tool_calls": len(tool_results),
            }
            
            logger.info(f"[{self.node_name}] 完成，迭代={iteration}, 工具调用={len(tool_results)}")
            
            return result
            
        except Exception as e:
            logger.error(f"[{self.node_name}] 执行错误: {e}")
            return {
                "success": False,
                "error": str(e),
                "errors": state.get("errors", []) + [{"node": self.node_name, "error": str(e)}],
            }
    
    async def run_legacy(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        Legacy 模式执行（子类可覆盖）
        
        默认调用不带工具的 LLM
        """
        logger.info(f"[{self.node_name}] 使用 Legacy 模式")
        
        system_prompt = self.get_system_prompt(state)
        user_message = self.get_user_message(state)
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
        
        response = await self.llm.ainvoke(messages)
        
        return await self.process_result(state, response.content, [])
    
    async def _execute_tool(self, tools: List, tool_name: str, tool_args: Dict[str, Any]) -> Any:
        """执行指定的工具"""
        import json
        
        # 预处理参数：解析 JSON 字符串
        processed_args = {}
        for key, value in tool_args.items():
            if isinstance(value, str):
                # 处理转义字符：将 \\n 替换为 \n
                processed_value_str = value.replace('\\n', '\n')
                
                # 尝试解析 JSON 字符串
                try:
                    processed_value = json.loads(processed_value_str)
                    processed_args[key] = processed_value
                except (json.JSONDecodeError, TypeError):
                    # 不是 JSON 字符串，保持原值
                    processed_args[key] = value
            else:
                processed_args[key] = value
        
        for tool in tools:
            if tool.name == tool_name:
                try:
                    result = await tool.ainvoke(processed_args)
                    return result
                except Exception as e:
                    logger.error(f"[{self.node_name}] 工具 {tool_name} 执行失败: {e}")
                    return {"error": str(e)}
        
        return {"error": f"未找到工具: {tool_name}"}
