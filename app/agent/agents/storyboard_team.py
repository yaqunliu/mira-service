"""
分镜团队 - Storyboard Team

负责将剧本转换为分镜脚本
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState
from app.agent.tools.generation_tools import (
    GenerateStoryboardImageTool,
    GeneratePromptTool
)
from app.core.logger import logger
from app.core.config import settings
import json


class StoryboardTeam:
    """分镜团队"""
    
    def __init__(self):
        """初始化分镜团队"""
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_SCENE_ANALYSIS,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.4
        )
        self.generate_image_tool = GenerateStoryboardImageTool()
        self.generate_prompt_tool = GeneratePromptTool()
        logger.info("分镜团队初始化完成")
    
    async def create_storyboards(
        self,
        state: ComicDramaState,
        shots_per_scene: int = 3
    ) -> Dict[str, Any]:
        """
        创建分镜脚本
        
        Args:
            state: 当前状态
            shots_per_scene: 每个场景的分镜数量
            
        Returns:
            分镜列表
        """
        script_text = state.get("script_text", "")
        characters = state.get("characters", [])
        scenes = state.get("scenes", [])
        
        if not script_text:
            return {
                "success": False,
                "error": "剧本内容为空",
                "storyboards": []
            }
        
        try:
            system_prompt = f"""你是一个专业的分镜师。请根据剧本内容创建详细的分镜脚本。

要求：
1. 将剧本分解为多个分镜
2. 每个分镜包含：场景名称、镜头描述、画面构图、角色动作、对话/旁白、时长估算
3. 确保分镜连贯流畅，符合剧本情节
4. 考虑画面美感和叙事节奏

请输出 JSON 格式：
{{
    "storyboards": [
        {{
            "id": "shot_1",
            "scene_index": 0,
            "scene_name": "场景名称",
            "shot_number": 1,
            "shot_type": "wide/medium/close-up/extreme_close-up",
            "camera_movement": "static/pan/tilt/dolly/zoom",
            "description": "画面描述",
            "action": "角色动作描述",
            "dialogue": "对话内容（可选）",
            "duration_seconds": 5,
            "characters_in_shot": ["角色名列表"],
            "mood": "画面情绪"
        }}
    ],
    "total_duration": "预估总时长"
}}"""

            context = f"""
剧本内容：
{script_text}

角色列表：{', '.join([c.get('name', '') for c in characters])}

场景列表：{', '.join([s.get('name', '') for s in scenes])}
"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=context)
            ]
            
            logger.info("开始创建分镜脚本...")
            
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
            
            storyboards = result.get("storyboards", [])
            
            logger.info(f"分镜脚本创建完成: {len(storyboards)} 个分镜")
            
            return {
                "success": True,
                "storyboards": storyboards,
                "total_duration": result.get("total_duration", "")
            }
            
        except Exception as e:
            logger.error(f"创建分镜脚本失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "storyboards": []
            }
    
    async def generate_storyboard_images(
        self,
        state: ComicDramaState,
        storyboard_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成分镜图片
        
        Args:
            state: 当前状态
            storyboard_id: 特定分镜 ID（可选，默认生成所有）
            
        Returns:
            生成结果
        """
        storyboards = state.get("storyboards", [])
        
        if not storyboards:
            return {"success": False, "error": "没有分镜数据"}
        
        target_storyboards = [
            sb for sb in storyboards
            if storyboard_id is None or sb.get("id") == storyboard_id
        ]
        
        results = []
        
        for sb in target_storyboards:
            if sb.get("image_url"):
                results.append({
                    "storyboard_id": sb.get("id"),
                    "success": True,
                    "image_url": sb.get("image_url")
                })
                continue
            
            try:
                description = sb.get("description", "")
                action = sb.get("action", "")
                
                full_description = f"{description} {action}"
                
                # 生成优化的提示词
                prompt_result = await self.generate_prompt_tool.execute(
                    state=state,
                    description=full_description,
                    prompt_type="image"
                )
                
                if prompt_result.get("success"):
                    image_result = await self.generate_image_tool.execute(
                        state=state,
                        storyboard_description=prompt_result.get("prompt", full_description)
                    )
                    
                    if image_result.get("success"):
                        sb["image_url"] = image_result.get("image_url")
                        sb["prompt_used"] = image_result.get("prompt_used")
                        
                        results.append({
                            "storyboard_id": sb.get("id"),
                            "success": True,
                            "image_url": image_result.get("image_url")
                        })
                    else:
                        results.append({
                            "storyboard_id": sb.get("id"),
                            "success": False,
                            "error": image_result.get("error")
                        })
                else:
                    results.append({
                        "storyboard_id": sb.get("id"),
                        "success": False,
                        "error": prompt_result.get("error")
                    })
                    
            except Exception as e:
                logger.error(f"生成分镜 {sb.get('id')} 图片失败: {e}")
                results.append({
                    "storyboard_id": sb.get("id"),
                    "success": False,
                    "error": str(e)
                })
        
        success_count = sum(1 for r in results if r.get("success"))
        
        return {
            "success": success_count > 0,
            "total": len(results),
            "success_count": success_count,
            "results": results
        }
    
    async def refine_storyboard(
        self,
        state: ComicDramaState,
        storyboard_id: str,
        feedback: str
    ) -> Dict[str, Any]:
        """
        根据反馈优化分镜
        
        Args:
            state: 当前状态
            storyboard_id: 分镜 ID
            feedback: 优化反馈
            
        Returns:
            优化后的分镜
        """
        storyboards = state.get("storyboards", [])
        storyboard = next((sb for sb in storyboards if sb.get("id") == storyboard_id), None)
        
        if not storyboard:
            return {"success": False, "error": f"分镜不存在: {storyboard_id}"}
        
        try:
            system_prompt = """你是一个专业的分镜师。请根据反馈优化分镜脚本。

请输出 JSON 格式：
{
    "optimized_storyboard": {
        "id": "分镜ID",
        "shot_type": "优化后的镜头类型",
        "camera_movement": "优化后的运镜方式",
        "description": "优化后的画面描述",
        "action": "优化后的动作描述",
        "duration_seconds": "优化后的时长"
    },
    "changes": "修改说明"
}"""

            context = f"""
当前分镜：
{json.dumps(storyboard, ensure_ascii=False, indent=2)}

用户反馈：{feedback}

请根据反馈优化分镜。
"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=context)
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
            optimized = result.get("optimized_storyboard", {})
            
            # 更新分镜
            for key, value in optimized.items():
                if key != "id":
                    storyboard[key] = value
            
            return {
                "success": True,
                "storyboard_id": storyboard_id,
                "optimized_storyboard": storyboard,
                "changes": result.get("changes", "")
            }
            
        except Exception as e:
            logger.error(f"优化分镜失败: {e}")
            return {"success": False, "error": str(e)}
    
    def calculate_total_duration(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        计算分镜总时长
        
        Args:
            state: 当前状态
            
        Returns:
            时长统计
        """
        storyboards = state.get("storyboards", [])
        
        total_seconds = sum(sb.get("duration_seconds", 5) for sb in storyboards)
        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        
        scene_durations = {}
        for sb in storyboards:
            scene_name = sb.get("scene_name", "unknown")
            if scene_name not in scene_durations:
                scene_durations[scene_name] = 0
            scene_durations[scene_name] += sb.get("duration_seconds", 5)
        
        return {
            "total_seconds": total_seconds,
            "formatted": f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒",
            "by_scene": scene_durations,
            "shot_count": len(storyboards)
        }


# 导出节点函数
async def create_storyboards_node(state: ComicDramaState) -> ComicDramaState:
    """
    LangGraph 节点：创建分镜
    """
    team = StoryboardTeam()
    
    result = await team.create_storyboards(state)
    
    storyboards = []
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    
    if result["success"]:
        storyboards = result["storyboards"]
        messages.append({
            "role": "system",
            "content": f"分镜脚本创建完成，共 {len(result['storyboards'])} 个分镜"
        })
        
        duration_info = team.calculate_total_duration(state)
        messages.append({
            "role": "system",
            "content": f"预估总时长: {duration_info['formatted']}"
        })
    else:
        errors.append(f"创建分镜失败: {result.get('error')}")
    
    return {
        "storyboards": storyboards,
        "messages": messages,
        "errors": errors
    }


async def generate_storyboard_images_node(state: ComicDramaState) -> ComicDramaState:
    """
    LangGraph 节点：生成分镜图片
    """
    team = StoryboardTeam()
    
    result = await team.generate_storyboard_images(state)
    
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    
    if result["success"]:
        messages.append({
            "role": "system",
            "content": f"分镜图片生成完成: {result['success_count']}/{result['total']}"
        })
    else:
        errors.append(f"生成分镜图片失败: {result.get('error')}")
    
    return {
        "messages": messages,
        "errors": errors
    }
