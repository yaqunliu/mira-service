"""
音频工程师 Node - Audio Engineer

负责为分镜生成配音音频。
管理批量音频生成任务。
"""

from typing import Dict, Any
from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.core.logger import logger


class AudioEngineerNode:
    """
    音频工程师 Node
    
    职责：
    1. 查询待配音的分镜
    2. 为每个分镜创建音频生成任务
    """
    
    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行音频处理
        
        Args:
            state: 当前状态
            
        Returns:
            执行结果
        """
        creation_uuid = state.get("creation_uuid")
        
        try:
            # 使用 Tool 查询待生成音频的分镜
            from app.agent.tools.db_tools import query_pending_audio_shots
            
            result = await query_pending_audio_shots.ainvoke({"creation_uuid": creation_uuid})
            
            if not result.get("success"):
                return {
                    "response_text": f"查询分镜失败：{result.get('error')}",
                    "production_stage": ProductionStage.STORYBOARD_READY,
                    "errors": [{"message": result.get("error")}],
                }
            
            audio_items = result.get("audio_items", [])
            
            if not audio_items:
                production_progress = dict(state.get("production_progress", {}))
                production_progress["audio_processing"] = {"status": "completed"}
                return {
                    "response_text": "所有音频已生成完成！请在分镜中试听确认。",
                    "production_stage": ProductionStage.AUDIO_READY,
                    "production_progress": production_progress,
                    "pending_approval": True,
                    "checkpoint_data": {
                        "checkpoint_type": "audio_confirmation",
                        "data": {},
                        "message": "请确认配音效果",
                    },
                }
            
            # 创建批量音频任务
            from app.agent.tasks.audio_tasks import agent_generate_batch_audio_task
            
            task = agent_generate_batch_audio_task.delay(
                creation_uuid=creation_uuid,
                audio_items=audio_items,
            )
            
            production_progress = dict(state.get("production_progress", {}))
            production_progress["audio_processing"] = {
                "status": "processing",
                "total": len(audio_items),
                "completed": 0,
                "task_id": task.id,
            }
            
            return {
                "response_text": f"""开始生成配音！

🎤 **共 {len(audio_items)} 条音频待生成**

音频生成需要一些时间，完成后我会通知您。""",
                "production_stage": ProductionStage.AUDIO_PROCESSING,
                "production_progress": production_progress,
                "pending_approval": False,
                "board_actions": [
                    {"type": "switch_view", "target": "storyboards"},
                ],
            }
            
        except Exception as e:
            logger.error(f"[AudioEngineer] 执行失败: {e}")
            return {
                "response_text": f"音频处理过程中出现错误：{str(e)}",
                "production_stage": ProductionStage.STORYBOARD_READY,
                "errors": [{"message": str(e)}],
            }


# 便捷函数
async def process_audio(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = AudioEngineerNode()
    return await node.run(state)
