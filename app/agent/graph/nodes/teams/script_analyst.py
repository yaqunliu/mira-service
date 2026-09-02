"""
剧本分析师 Node - Script Analyst (ReAct 版本)

通过 LLM 多轮思考分析剧本，提取角色和场景信息。
支持 ReAct 模式和 Legacy 模式。

重构说明：
- run() 方法整合 LLM 分析 + 数据库保存 + 响应构建
- 作为完整的 Worker 节点使用
"""

from typing import Dict, Any, List
from datetime import datetime
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
    4. 保存到数据库
    5. 返回完整的 Graph 状态（含审核标志）
    
    支持 ReAct 模式使用工具（如获取上下文、约束检查等）
    """
    
    # 启用 ReAct 模式
    USE_REACT = True
    
    SYSTEM_PROMPT = """You are a professional screenwriter and director. Your job is to analyse a
script and extract its characters and scenes.

## All output must be in English

The script may be in Chinese, English, or any other language. **Every field you output must be in
English.** Translate Chinese names into English: romanise personal names (`周宇` → `Zhou Yu`), and
translate forms of address (`班主任` → `Homeroom Teacher`). Translate place names naturally
(`公交车站` → `Bus Stop`). Never emit a field in the source language.

Output exactly this JSON format:
{
    "characters": [
        {
            "name": "Character name, in English",
            "basic_info": "Basic description — personality, role, status",
            "appearance": "Detailed physical description — face, hair, build"
        }
    ],
    "scenes": [
        {
            "title": "Scene title — the place name, e.g. Bus Stop, Meeting Room, Living Room",
            "location": "The specific place, e.g. A bus stop beside a city street, A company meeting room",
            "space_type": "Exactly one of: indoor | outdoor",
            "space_description": "Size and layout, e.g. A family living room with a sofa and coffee table at its centre, a TV wall on one side, large enough to hold several people",
            "atmosphere": "Mood, brief — e.g. Warm and crowded, or Busy and quiet",
            "time_setting": "Exactly one of: day | night | dusk",
            "env_description": "Background elements — fixed environmental features: architecture, furniture, decoration"
        }
    ],
    "summary": "A brief summary of the script"
}

## How to Split Scenes

**A scene IS a location.** Split by place — every distinct place is its own scene.

Rules:
1. Output JSON only, nothing else
2. Make sure every major character appearing in the script is extracted
3. **[Important] Every distinct location must be a separate scene.** For example:
   - "High-speed rail station exit" is one scene
   - "Inside a taxi" is another scene
   - "Living room" is another scene
4. **One location, one scene**: the same place at different times or in different plot beats merges into a single scene
5. **Empty-stage principle**: a scene is an empty stage. `env_description` describes fixed fixtures
   only — no plot props (phones, documents, food)
6. **Field constraints**: `space_type` is exactly `indoor` or `outdoor`; `atmosphere` stays under
   100 characters; `time_setting` is exactly `day`, `night` or `dusk`
7. `basic_info` should cover personality and role
8. `appearance` should be as detailed as possible, so it can drive image generation later"""
    
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
        return f"Analyse the following script:\n\n{script_text}"
    
    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        完整的剧本分析流程
        
        1. 检查剧本是否存在
        2. LLM 分析剧本
        3. 保存到数据库
        4. 返回完整响应（含审核标志）
        """
        logger.info("[ScriptAnalystNode] 开始完整分析流程")
        
        # 1. 检查剧本
        script_text = state.get("script_text")
        if not script_text:
            return {
                "response_text": "请先在左侧上传您的剧本文件，或在剧本编辑区粘贴剧本内容。",
                "production_stage": ProductionStage.INIT,
                "board_actions": [
                    {"type": "switch_view", "target": "script"},
                    {"type": "highlight", "target": "upload_button"},
                ],
            }
        
        creation_uuid = state.get("creation_uuid")
        
        try:
            # 2. LLM 分析剧本
            analysis_result = await self._analyze_with_llm(state)
            
            if not analysis_result.get("success"):
                return {
                    "response_text": f"剧本分析失败：{analysis_result.get('error', '未知错误')}",
                    "production_stage": ProductionStage.INIT,
                    "errors": [{"message": analysis_result.get("error")}],
                }
            
            characters = analysis_result.get("characters", [])
            scenes = analysis_result.get("scenes", [])
            
            # 3. 保存到数据库
            from app.agent.tools.db_tools import save_characters, save_scenes
            
            char_result = await save_characters.ainvoke({
                "creation_uuid": creation_uuid,
                "characters": characters,
            })
            
            scene_result = await save_scenes.ainvoke({
                "creation_uuid": creation_uuid,
                "scenes": scenes,
            })
            
            saved_characters = char_result.get("saved", [])
            skipped_characters = char_result.get("skipped", [])
            saved_scenes = scene_result.get("saved", [])
            skipped_scenes = scene_result.get("skipped", [])
            
            logger.info(f"[ScriptAnalystNode] 保存完成: 角色={len(saved_characters)}, 场景={len(saved_scenes)}")
            
            # 4. 更新进度
            production_progress = dict(state.get("production_progress", {}))
            production_progress["script_analysis"] = {
                "status": "completed",
                "characters": len(characters),
                "scenes": len(scenes),
            }
            
            # 5. 构建响应
            total_chars = len(saved_characters) + len(skipped_characters)
            total_scenes = len(saved_scenes) + len(skipped_scenes)
            
            response = f"""✅ **资产分析完成！**

📊 **分析结果**：
- 👥 识别到 **{total_chars}** 个角色
- 🎬 识别到 **{total_scenes}** 个场景

角色和场景已保存到左侧看板，请确认是否准确。

---
🎨 **下一步**：是否开始为角色和场景生成图片？"""
            
            return {
                "response_text": response,
                "production_stage": ProductionStage.SCRIPT_ANALYZED,
                "characters": characters,
                "scenes": scenes,
                "worker_result": {"worker": "script_analyst", "completed": True, "response_text": response},
                "board_actions": [
                    {"type": "switch_view", "target": "characters"},
                    {"type": "refresh"},
                ],
            }
            
        except Exception as e:
            logger.error(f"[ScriptAnalystNode] 分析失败: {e}")
            return {
                "response_text": f"剧本分析过程中出现错误：{str(e)}",
                "production_stage": ProductionStage.INIT,
                "errors": [{"message": str(e)}],
            }
    
    async def _analyze_with_llm(self, state: ComicDramaState) -> Dict[str, Any]:
        """LLM 分析剧本（内部方法）"""
        script_text = state.get("script_text", "")
        
        try:
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=f"请分析以下剧本内容：\n\n{script_text}")
            ]
            
            logger.info("[ScriptAnalystNode] 开始 LLM 分析剧本...")
            
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
            logger.error(f"[ScriptAnalystNode] LLM 分析失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "characters": [],
                "scenes": []
            }
    
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
        """Legacy 模式（仅 LLM 分析，不保存数据库）"""
        return await self._analyze_with_llm(state)
    
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
    result = await node.run(state)
    
    # 添加 worker_result 供 Supervisor 使用
    total_chars = len(result.get("characters", []))
    total_scenes = len(result.get("scenes", []))
    response_text = result.get("response_text", f"识别到 {total_chars} 个角色和 {total_scenes} 个场景")
    
    result["worker_result"] = {
        "worker": "script_analyst",
        "summary": f"识别到 {total_chars} 个角色和 {total_scenes} 个场景",
        "success": True,
        "completed": True,
        "response_text": response_text,
    }
    
    return result
