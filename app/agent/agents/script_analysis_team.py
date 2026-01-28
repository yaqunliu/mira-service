"""
剧本分析团队 - Script Analysis Team

负责剧本解析、角色提取、场景提取
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger
from app.core.config import settings
import json


class ScriptAnalysisTeam:
    """剧本分析团队"""
    
    def __init__(self):
        """初始化分析团队"""
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_CHARACTER_ANALYSIS,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3
        )
        logger.info("剧本分析团队初始化完成")
    
    async def analyze_script(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        分析剧本，提取角色和场景
        
        Args:
            state: 当前状态
            
        Returns:
            分析结果，包含角色列表和场景列表
        """
        script_text = state.get("script_text", "")
        
        if not script_text:
            return {
                "success": False,
                "error": "剧本内容为空",
                "characters": [],
                "scenes": []
            }
        
        try:
            # 构建分析提示词
            system_prompt = """你是一个专业的剧本分析专家。请分析提供的剧本内容，提取所有角色和场景信息。

请按以下 JSON 格式输出：
{
    "characters": [
        {
            "name": "角色名称",
            "description": "角色描述（外貌、性格等）",
            "appearance": "外貌特征详细描述",
            "personality": "性格特点",
            "role_type": " protagonist|supporting|antagonist|minor",
            "importance": "主要角色数量（1-5，5为最重要）"
        }
    ],
    "scenes": [
        {
            "name": "场景名称",
            "description": "场景描述",
            "location": "地点",
            "time": "时间（白天/夜晚/黄昏等）",
            "mood": "氛围（紧张/轻松/悲伤等）",
            "characters_involved": ["涉及的角色名称列表"]
        }
    ],
    "summary": "剧本简要总结"
}

注意：
1. 只输出 JSON，不要其他内容
2. 确保所有在剧本中出现的角色都被提取
3. 场景应该按照剧本的时间顺序排列
4. 角色重要性根据出场频率和剧情作用判断"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"请分析以下剧本内容：\n\n{script_text}")
            ]
            
            logger.info("开始分析剧本...")
            
            response = await self.llm.ainvoke(messages)
            content = response.content
            
            # 解析 JSON 响应
            try:
                # 尝试从代码块中提取
                import re
                json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = content
                
                result = json.loads(json_str)
                
                logger.info(
                    f"剧本分析完成: "
                    f"characters={len(result.get('characters', []))}, "
                    f"scenes={len(result.get('scenes', []))}"
                )
                
                return {
                    "success": True,
                    "characters": result.get("characters", []),
                    "scenes": result.get("scenes", []),
                    "summary": result.get("summary", "")
                }
                
            except json.JSONDecodeError as e:
                logger.error(f"解析剧本分析结果失败: {e}")
                return {
                    "success": False,
                    "error": f"JSON 解析失败: {str(e)}",
                    "raw_response": content,
                    "characters": [],
                    "scenes": []
                }
                
        except Exception as e:
            logger.error(f"剧本分析失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "characters": [],
                "scenes": []
            }
    
    async def extract_dialogues(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        提取剧本中的对话
        
        Args:
            state: 当前状态
            
        Returns:
            对话列表
        """
        script_text = state.get("script_text", "")
        
        try:
            system_prompt = """请从剧本中提取所有对话，按场景分组。

输出格式：
{
    "dialogues": [
        {
            "scene_index": 0,
            "scene_name": "场景名称",
            "lines": [
                {
                    "character": "角色名",
                    "text": "对话内容",
                    "emotion": "情绪（可选）"
                }
            ]
        }
    ]
}"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"请提取以下剧本中的对话：\n\n{script_text}")
            ]
            
            response = await self.llm.ainvoke(messages)
            content = response.content
            
            # 解析 JSON
            import re
            json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content
            
            result = json.loads(json_str)
            
            return {
                "success": True,
                "dialogues": result.get("dialogues", [])
            }
            
        except Exception as e:
            logger.error(f"提取对话失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "dialogues": []
            }
    
    async def analyze_character_relationships(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        分析角色关系
        
        Args:
            state: 当前状态
            
        Returns:
            角色关系图
        """
        script_text = state.get("script_text", "")
        characters = state.get("characters", [])
        
        if not characters:
            return {
                "success": False,
                "error": "没有角色信息",
                "relationships": []
            }
        
        try:
            character_names = [c.get("name", "") for c in characters]
            
            system_prompt = f"""分析剧本中以下角色之间的关系：{', '.join(character_names)}

输出格式：
{{
    "relationships": [
        {{
            "from": "角色A",
            "to": "角色B",
            "type": "关系类型（朋友/敌人/恋人/家人等）",
            "description": "关系描述"
        }}
    ]
}}"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"请分析以下剧本中的角色关系：\n\n{script_text}")
            ]
            
            response = await self.llm.ainvoke(messages)
            content = response.content
            
            # 解析 JSON
            import re
            json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content
            
            result = json.loads(json_str)
            
            return {
                "success": True,
                "relationships": result.get("relationships", [])
            }
            
        except Exception as e:
            logger.error(f"分析角色关系失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "relationships": []
            }


# 导出函数
async def analyze_script_node(state: ComicDramaState) -> ComicDramaState:
    """
    LangGraph 节点：分析剧本
    
    这是 LangGraph 工作流中的节点函数
    """
    team = ScriptAnalysisTeam()
    
    result = await team.analyze_script(state)
    
    characters = []
    scenes = []
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    
    if result["success"]:
        characters = result["characters"]
        scenes = result["scenes"]
        messages.append({
            "role": "system",
            "content": f"剧本分析完成。识别到 {len(result['characters'])} 个角色，{len(result['scenes'])} 个场景。"
        })
    else:
        errors.append(f"剧本分析失败: {result.get('error')}")
    
    return {
        "characters": characters,
        "scenes": scenes,
        "messages": messages,
        "errors": errors
    }
