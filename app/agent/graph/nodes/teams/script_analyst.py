"""
剧本分析师 Node - Script Analyst

通过 LLM 多轮思考分析剧本，提取角色和场景信息。
不依赖任何分析类 Tool，直接由 LLM 完成分析工作。
"""

from typing import Dict, Any
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger
from app.core.config import settings
import json
import re


class ScriptAnalystNode:
    """
    剧本分析师 Node
    
    职责：
    1. 通过 LLM 分析剧本文本
    2. 提取角色信息（name, basic_info, appearance）
    3. 提取场景信息（title, location, atmosphere, time_setting）
    """
    
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
        """初始化 LLM"""
        self.llm = ChatOpenAI(
            model="Qwen/Qwen-Plus",  # 使用更稳定的 Qwen 模型
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3,
            timeout=60,  # 60秒超时
            max_retries=2,  # 最多重试2次
        )
    
    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行剧本分析
        
        Args:
            state: 包含 script_text 的状态
            
        Returns:
            {success, characters, scenes, summary} 或 {success: False, error}
        """
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
            
            # 使用 stream 模式，实时打印输出
            content_chunks = []
            async for chunk in self.llm.astream(messages):
                chunk_text = chunk.content
                if chunk_text:
                    content_chunks.append(chunk_text)
                    # 实时打印到日志
                    logger.debug(f"[LLM Stream] {chunk_text}")
            
            content = "".join(content_chunks)
            logger.info(f"[ScriptAnalystNode] LLM 响应完成，长度: {len(content)} 字符")
            
            # 解析 JSON 响应
            result = self._parse_json_response(content)
            
            if result is None:
                return {
                    "success": False,
                    "error": "JSON 解析失败",
                    "raw_response": content,
                    "characters": [],
                    "scenes": []
                }
            
            characters = result.get("characters", [])
            scenes = result.get("scenes", [])
            summary = result.get("summary", "")
            
            logger.info(
                f"[ScriptAnalystNode] 分析完成: "
                f"角色={len(characters)}, 场景={len(scenes)}"
            )
            
            return {
                "success": True,
                "characters": characters,
                "scenes": scenes,
                "summary": summary
            }
            
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
