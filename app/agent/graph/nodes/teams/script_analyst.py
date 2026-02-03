"""
剧本分析师 Node - Script Analyst (ReAct 版本)

通过 LLM 多轮思考分析剧本，提取角色和场景信息。
支持 ReAct 模式和 Legacy 模式。
"""

from typing import Dict, Any, List
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.core.logger import logger
from app.core.config import settings
import json
import re


class ScriptAnalystNode(ReActWorkerNode):
    """
    剧本分析师 Node (ReAct 版本)
    
    职责：
    1. 通过 LLM 分析剧本文本
    2. 提取角色信息（name, basic_info, appearance）
    3. 提取场景信息（title, location, atmosphere, time_setting）
    
    支持 ReAct 模式使用工具（如获取上下文、约束检查等）
    """
    
    # 启用 ReAct 模式
    USE_REACT = True
    
    SYSTEM_PROMPT = """你是一名专业的编剧和导演，负责分析剧本内容，提取角色和场景信息。

请按以下 JSON 格式输出：
{
    "characters": [
        {
            "name": "角色名称",
            "basic_info": "角色基本描述（性格、身份等）",
            "appearance": "外貌特征详细描述（脸型、发型、体型等）"
        }
    ],
    "scenes": [
        {
            "title": "场景标题（地点名称，如：公交车站、会议室、客厅等）",
            "location": "具体地点名称（如：城市街道旁的公交车站、公司会议室等）",
            "space_type": "空间类型（只填：室内 或 室外）",
            "space_description": "空间描述（空间大小和布局，如：家庭客厅，中央有沙发和茶几，电视墙一面，空间较大以容纳多人）",
            "atmosphere": "氛围（简短，如：暖间拥挤 或 繁忙安静）",
            "time_setting": "时间（只填：日间 或 夜间 或 黄昏）",
            "env_description": "背景元素（固定的环境元素：建筑、家具、装饰等）"
        }
    ],
    "summary": "剧本简要总结"
}

## 场景划分标准

**场景 = 地点**：场景应该按照**地点**来划分，每个不同的地点都是独立的场景。

注意：
1. 只输出 JSON，不要其他内容
2. 确保所有在剧本中出现的主要角色都被提取
3. **【重要】每个不同的地点必须作为独立的场景！** 例如：
   - "高铁站出站口" 是一个场景
   - "出租车内" 是另一个场景  
   - "客厅" 是另一个场景
4. **同一地点只有一个场景**：同一地点的不同时间、不同剧情都合并为一个场景
5. **空舞台原则**：场景是空舞台，env_description 只描述固定设施，不包含剧情道具（手机、文件、食物等）
6. **字段长度限制**：space_type 只填"室内"或"室外"，atmosphere 控制在20字以内，time_setting 只填"日间"或"夜间"或"黄昏"
7. 角色 basic_info 应包含性格和身份描述
8. 角色 appearance 应尽量详细，便于后续生成形象图片"""
    
    def __init__(self):
        """初始化"""
        super().__init__(model="Qwen/Qwen-Plus", temperature=0.3)
    
    def get_system_prompt(self, state: ComicDramaState) -> str:
        """获取系统提示词"""
        return self.SYSTEM_PROMPT
    
    def get_tools(self) -> List:
        """获取可用工具（Legacy 模式下不使用）"""
        return []
    
    def get_user_message(self, state: ComicDramaState) -> str:
        """获取用户消息（剧本内容）"""
        script_text = state.get("script_text", "")
        return f"请分析以下剧本内容：\n\n{script_text}"
    
    async def process_result(self, state: ComicDramaState, final_response: str, tool_results: List[Dict]) -> Dict[str, Any]:
        """处理分析结果"""
        if not final_response:
            return {
                "success": False,
                "error": "LLM 响应为空",
                "characters": [],
                "scenes": []
            }
        
        # 解析 JSON
        result = self._parse_json_response(final_response)
        
        if result is None:
            return {
                "success": False,
                "error": "JSON 解析失败",
                "raw_response": final_response,
                "characters": [],
                "scenes": []
            }
        
        characters = result.get("characters", [])
        scenes = result.get("scenes", [])
        summary = result.get("summary", "")
        
        logger.info(f"[ScriptAnalystNode] 分析完成: 角色={len(characters)}, 场景={len(scenes)}")
        
        return {
            "success": True,
            "characters": characters,
            "scenes": scenes,
            "summary": summary
        }
    
    async def run_legacy(self, state: ComicDramaState) -> Dict[str, Any]:
        """Legacy 模式（Stream 输出）"""
        script_text = state.get("script_text", "")
        
        if not script_text:
            logger.warning("[ScriptAnalystNode] 剧本内容为空")
            return {
                "success": False,
                "error": "剧本内容为空",
                "characters": [],
                "scenes": []
            }
        
        try:
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=f"请分析以下剧本内容：\n\n{script_text}")
            ]
            
            logger.info("[ScriptAnalystNode] 开始 LLM 分析剧本 (stream 模式)...")
            
            # Stream 模式
            content_chunks = []
            async for chunk in self.llm.astream(messages):
                chunk_text = chunk.content
                if chunk_text:
                    content_chunks.append(chunk_text)
            
            content = "".join(content_chunks)
            logger.info(f"[ScriptAnalystNode] LLM 响应完成，长度: {len(content)} 字符")
            
            return await self.process_result(state, content, [])
            
        except Exception as e:
            logger.error(f"[ScriptAnalystNode] 分析失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "characters": [],
                "scenes": []
            }
    
    def _parse_json_response(self, content: str) -> Dict[str, Any] | None:
        """解析 LLM 返回的 JSON"""
        try:
            # 尝试从 markdown 代码块中提取
            json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content
            
            return json.loads(json_str)
            
        except json.JSONDecodeError as e:
            logger.error(f"[ScriptAnalystNode] JSON 解析失败: {e}")
            return None


# 便捷函数
async def analyze_script(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = ScriptAnalystNode()
    return await node.run(state)
