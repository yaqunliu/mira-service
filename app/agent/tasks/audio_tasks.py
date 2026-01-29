"""
Agent 专用音频生成 Tasks

⚠️ 核心原则：这些 Tasks 独立于现有的音频任务
"""

from typing import Dict, Any, Optional, List

from app.core.celery_app import celery_app
from app.core.logger import logger


@celery_app.task(bind=True, name="agent.generate_audio")
def agent_generate_audio_task(
    self,
    creation_uuid: str,
    shot_id: int,
    text: str,
    voice_id: str,
    audio_type: str = "dialogue",  # "dialogue", "narration", "bgm"
    speed: float = 1.0,
    pitch: float = 1.0,
) -> Dict[str, Any]:
    """
    Agent 专用音频生成任务
    
    Args:
        creation_uuid: 创作项目 UUID
        shot_id: 分镜 ID
        text: 要转换的文本
        voice_id: 语音模型 ID（Fish Audio）
        audio_type: 音频类型（dialogue=对话, narration=旁白, bgm=背景音乐）
        speed: 语速（0.5-2.0）
        pitch: 音调（0.5-2.0）
        
    Returns:
        {
            "status": "success" | "failed",
            "shot_id": int,
            "audio_url": str,
            "duration": float,
            "error": str  # 仅失败时
        }
    """
    try:
        logger.info(f"[Agent Task] 开始生成音频: shot_id={shot_id}, type={audio_type}")
        
        self.update_state(state='PROGRESS', meta={
            'progress': 10,
            'status': '开始生成音频...',
            'shot_id': shot_id,
            'audio_type': audio_type,
        })
        
        from app.services.audio_generation import AudioGenerationService
        
        audio_service = AudioGenerationService()
        
        self.update_state(state='PROGRESS', meta={
            'progress': 30,
            'status': '调用语音合成服务...',
            'shot_id': shot_id,
        })
        
        result = audio_service.generate(
            text=text,
            voice_id=voice_id,
            speed=speed,
            pitch=pitch,
        )
        
        self.update_state(state='PROGRESS', meta={
            'progress': 80,
            'status': '保存结果到数据库...',
            'shot_id': shot_id,
        })
        
        # 更新数据库
        from app.db.session import get_sync_session
        from app.models.shot import Shot
        
        with get_sync_session() as db:
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                extra_data = shot.extra_data or {}
                
                if audio_type == "dialogue":
                    extra_data["dialogue_audio_url"] = result["url"]
                elif audio_type == "narration":
                    extra_data["narration_audio_url"] = result["url"]
                else:
                    extra_data["bgm_audio_url"] = result["url"]
                
                extra_data["audio_duration"] = result.get("duration", 0)
                shot.extra_data = extra_data
                db.commit()
        
        logger.info(f"[Agent Task] 音频生成成功: shot_id={shot_id}")
        
        return {
            "status": "success",
            "shot_id": shot_id,
            "audio_type": audio_type,
            "audio_url": result["url"],
            "duration": result.get("duration", 0),
        }
        
    except Exception as e:
        logger.error(f"[Agent Task] 音频生成失败: {e}")
        return {
            "status": "failed",
            "shot_id": shot_id,
            "audio_type": audio_type,
            "error": str(e),
            "recoverable": True,
        }


@celery_app.task(bind=True, name="agent.generate_batch_audio")
def agent_generate_batch_audio_task(
    self,
    creation_uuid: str,
    audio_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    批量音频生成任务
    
    Args:
        creation_uuid: 创作项目 UUID
        audio_items: 音频项列表
            [
                {"shot_id": 1, "text": "...", "voice_id": "...", "audio_type": "dialogue"},
                ...
            ]
        
    Returns:
        {
            "status": "success" | "partial" | "failed",
            "results": [...],
            "success_count": int,
            "failed_count": int,
        }
    """
    try:
        logger.info(f"[Agent Task] 开始批量生成音频: {len(audio_items)} 条")
        
        from app.services.audio_generation import AudioGenerationService
        
        audio_service = AudioGenerationService()
        results = []
        success_count = 0
        failed_count = 0
        
        for i, item in enumerate(audio_items):
            progress = int((i / len(audio_items)) * 90) + 5
            self.update_state(state='PROGRESS', meta={
                'progress': progress,
                'status': f'生成第 {i+1}/{len(audio_items)} 条音频...',
                'current_shot_id': item.get("shot_id"),
            })
            
            try:
                result = audio_service.generate(
                    text=item["text"],
                    voice_id=item["voice_id"],
                    speed=item.get("speed", 1.0),
                    pitch=item.get("pitch", 1.0),
                )
                
                results.append({
                    "shot_id": item["shot_id"],
                    "status": "success",
                    "audio_url": result["url"],
                    "duration": result.get("duration", 0),
                })
                success_count += 1
                
            except Exception as e:
                results.append({
                    "shot_id": item["shot_id"],
                    "status": "failed",
                    "error": str(e),
                })
                failed_count += 1
        
        status = "success" if failed_count == 0 else "partial" if success_count > 0 else "failed"
        
        logger.info(f"[Agent Task] 批量音频生成完成: success={success_count}, failed={failed_count}")
        
        return {
            "status": status,
            "results": results,
            "success_count": success_count,
            "failed_count": failed_count,
        }
        
    except Exception as e:
        logger.error(f"[Agent Task] 批量音频生成失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "results": [],
            "success_count": 0,
            "failed_count": len(audio_items),
        }
