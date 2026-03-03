"""
Vocab 视频生成工具 - 每个分镜单独提交到 Celery 队列

将视频生成任务提交到 Celery 队列异步执行
"""

from typing import Dict, Any, List, Optional

from langchain_core.tools import tool

from app.core.logger import logger


@tool
async def submit_vocab_video_generation(
    shot_ids: List[int],
    model: str = "viduq2",
) -> Dict[str, Any]:
    """
    提交 Vocab 视频生成任务 - 每个分镜单独提交

    Args:
        shot_ids: 分镜ID列表
        model: 视频模型，可选:
            - viduq2 (Vidu 参考图生视频，默认)
            - viduq2-pro (Vidu Pro)
            - viduq2-turbo (Vidu Turbo)
            - doubao-seedance-1-5-pro-251215 (Seedance 1.5 文生视频)
            - sora-2 (Sora2 文生视频)

    Returns:
        {
            "success": True,
            "task_ids": ["task_id1", "task_id2", ...],
            "message": "已提交 N 个视频生成任务"
        }
    """
    logger.info(f"[VocabVideoGen] 提交视频生成任务: shot_ids={shot_ids}, model={model}")
    
    from app.tasks.vocab_video_gen import generate_single_vocab_video_task
    
    task_ids = []
    for shot_id in shot_ids:
        task = generate_single_vocab_video_task.delay(shot_id, model)
        task_ids.append(task.id)
        logger.info(f"[VocabVideoGen] 提交分镜 {shot_id} 的视频生成任务: task_id={task.id}")
    
    logger.info(f"[VocabVideoGen] 共提交 {len(task_ids)} 个任务")
    
    return {
        "success": True,
        "task_ids": task_ids,
        "message": f"已提交 {len(shot_ids)} 个视频生成任务"
    }


submit_vocab_video_generation_tool = submit_vocab_video_generation
