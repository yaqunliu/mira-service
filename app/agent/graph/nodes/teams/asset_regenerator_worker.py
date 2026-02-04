"""
Asset Regenerator Worker Node - 资产重新生成 Worker (ReAct 版本)

职责：
1. 分析用户意图（操作类型、目标资源）
2. 调用 Tools 查询资源信息
3. 调用 Tools 执行重新生成

基于 ReActWorkerNode 实现，支持多轮思考和工具调用。
"""

from typing import Dict, Any, List
from datetime import datetime

from app.agent.state.schemas import ComicDramaState
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.core.logger import logger


class AssetRegeneratorWorkerNode(ReActWorkerNode):
    """
    资产重新生成 Worker Node (ReAct 版本)
    
    职责：
    1. 解析用户意图：要重新生成什么类型的资产
    2. 确定目标资源：哪些角色/场景/分镜
    3. 确定操作参数：首帧/尾帧/视频/提示词等
    4. 调用 Tools 执行重新生成
    
    使用 ReAct 循环：
    - Thought: 分析用户意图
    - Action: 调用 Tool 查询/执行
    - Observation: 观察结果
    - 循环直到完成
    """
    
    USE_REACT = True
    
    def __init__(self):
        super().__init__(model="Qwen/Qwen-Plus", temperature=0.3)
    
    def get_system_prompt(self, state: ComicDramaState) -> str:
        """
        获取系统提示词
        
        根据用户消息检测目标类型，加载对应的提示词模板
        """
        user_message = state.get("user_message", "")
        target_type = self._detect_target_type(user_message)
        
        from app.utils.file_utils import read_prompt_file
        
        if target_type == "character":
            return read_prompt_file("agent_regenerate_character.md")
        elif target_type == "scene":
            return read_prompt_file("agent_regenerate_scene.md")
        else:  # shot
            return read_prompt_file("agent_regenerate_shot.md")
    
    def _detect_target_type(self, user_message: str) -> str:
        """
        检测目标类型（角色/场景/分镜）
        
        根据用户消息内容判断要操作的资源类型
        """
        msg_lower = user_message.lower()
        
        # 角色关键词
        if any(kw in msg_lower for kw in ["角色", "人物", "演员"]):
            return "character"
        
        # 场景关键词
        if any(kw in msg_lower for kw in ["场景", "背景", "环境"]):
            return "scene"
        
        # 分镜关键词或默认
        return "shot"
    
    def get_tools(self) -> List:
        """获取可用工具列表"""
        from app.agent.tools.db_tools import (
            query_characters,
            query_scenes,
            query_shots,
        )
        from app.agent.tools.regenerate_worker_tools import (
            query_single_character,
            query_single_scene,
            query_single_shot,
            submit_character_image_regeneration,
            submit_character_prompt_regeneration,
            submit_scene_image_regeneration,
            submit_scene_prompt_regeneration,
            submit_shot_image_regeneration,
            submit_shot_prompt_regeneration,
            submit_shot_video_regeneration,
        )
        
        return [
            # 查询类
            query_characters,
            query_scenes,
            query_shots,
            query_single_character,
            query_single_scene,
            query_single_shot,
            # 提交重新生成类
            submit_character_image_regeneration,
            submit_character_prompt_regeneration,
            submit_scene_image_regeneration,
            submit_scene_prompt_regeneration,
            submit_shot_image_regeneration,
            submit_shot_prompt_regeneration,
            submit_shot_video_regeneration,
        ]
    
    async def process_result(self, state: ComicDramaState, final_response: str, tool_results: List[Dict]) -> Dict[str, Any]:
        """
        处理 ReAct 循环的最终结果
        
        Args:
            state: 当前状态
            final_response: LLM 的最终回复
            tool_results: 所有工具调用结果
            
        Returns:
            更新后的状态
        """
        logger.info(f"[{self.node_name}] 处理结果，工具调用次数: {len(tool_results)}")
        
        # 分析工具结果，统计成功/失败
        success_count = 0
        failed_count = 0
        
        for result in tool_results:
            if result.get("tool", "").startswith("submit_"):
                if result.get("result", {}).get("success", False):
                    success_count += 1
                else:
                    failed_count += 1
        
        # 构建响应消息
        if success_count > 0 and failed_count == 0:
            response_text = f"✅ 已成功提交 {success_count} 个重新生成任务。"
        elif success_count > 0 and failed_count > 0:
            response_text = f"✅ 已提交 {success_count} 个任务，❌ {failed_count} 个失败。"
        elif failed_count > 0:
            response_text = f"❌ 提交失败，共 {failed_count} 个任务失败。"
        else:
            response_text = final_response if final_response else "未执行任何操作。"
        
        # 添加详细结果
        if tool_results:
            response_text += "\n\n**执行详情：**"
            for result in tool_results:
                tool_name = result.get("tool", "unknown")
                tool_result = result.get("result", {})
                
                if tool_name.startswith("submit_character"):
                    char_id = tool_result.get("character_id")
                    success = tool_result.get("success", False)
                    response_text += f"\n- 角色 {char_id}: {'成功' if success else '失败'}"
                    
                elif tool_name.startswith("submit_scene"):
                    scene_id = tool_result.get("scene_id")
                    success = tool_result.get("success", False)
                    response_text += f"\n- 场景 {scene_id}: {'成功' if success else '失败'}"
                    
                elif tool_name.startswith("submit_shot"):
                    shot_id = tool_result.get("shot_id")
                    success = tool_result.get("success", False)
                    prompt_type = tool_result.get("prompt_type", "")
                    frame_type = tool_result.get("frame_type", "")
                    knowledge_used = tool_result.get("knowledge_used", False)
                    
                    detail = f"分镜 {shot_id}"
                    if prompt_type:
                        detail += f" ({prompt_type}"
                        if frame_type:
                            detail += f"-{frame_type}"
                        detail += ")"
                    if knowledge_used:
                        detail += " [知识库增强]"
                    detail += f": {'成功' if success else '失败'}"
                    
                    response_text += f"\n- {detail}"
        
        return {
            "success": success_count > 0,
            "response_text": response_text,
            "regenerated_count": success_count,
            "failed_count": failed_count,
            "tool_results": tool_results,
            "worker_result": {
                "worker": "asset_regenerator",
                "summary": f"提交了 {success_count} 个重新生成任务",
                "success": success_count > 0,
                "completed": True,
                "response_text": response_text,
            },
        }


# 便捷函数
async def regenerate_assets_worker(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = AssetRegeneratorWorkerNode()
    return await node.run(state)
