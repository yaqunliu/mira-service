<<<<<<< Updated upstream
<<<<<<< Updated upstream
<<<<<<< Updated upstream
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
        
=======
=======
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes



@celery_app.task(bind=True, name="agent.generate_shot_audio_batch")
def agent_generate_shot_audio_batch_task(
    self,
    creation_uuid: str,
    shot_ids: List[int],
    force_regenerate: bool = False,
) -> Dict[str, Any]:
    """
    批量生成 Shot 的 Narration 音频任务

    使用 GenerateNarrationAudioBatchTool 为每个 shot 的 narration 数组生成音频：
    1. 解析 narration 数组
    2. 根据说话者获取 voice_id 和 voice_speed
    3. 根据情绪添加情感标签
    4. 生成音频并上传到 US3
    5. 保存音频 URL 到 shot.audio_url
    6. 保存音频历史到 shot.extra_data["audio_historys"]

    Args:
        creation_uuid: 创作项目 UUID
        shot_ids: Shot ID 列表
        force_regenerate: 是否强制重新生成

<<<<<<< Updated upstream
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
    Returns:
        {
            "status": "success" | "partial" | "failed",
            "results": [...],
            "success_count": int,
            "failed_count": int,
        }
    """
    try:
<<<<<<< Updated upstream
<<<<<<< Updated upstream
<<<<<<< Updated upstream
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
=======
=======
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
        logger.info(f"[Agent Task] 开始批量生成 Shot 音频: {len(shot_ids)} shots")

        import asyncio
        from app.agent.tools.audio_tools import GenerateNarrationAudioBatchTool
        from app.agent.state.schemas import ComicDramaState

        # 创建工具实例
        audio_batch_tool = GenerateNarrationAudioBatchTool()

        # 创建状态对象
        state = ComicDramaState(creation_uuid=creation_uuid)

        results = []
        success_count = 0
        failed_count = 0

        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        for i, shot_id in enumerate(shot_ids):
            progress = int((i / len(shot_ids)) * 90) + 5
            self.update_state(state='PROGRESS', meta={
                'progress': progress,
                'status': f'生成第 {i+1}/{len(shot_ids)} 个分镜音频...',
                'current_shot_id': shot_id,
            })

            try:
                # 调用异步工具生成音频
                result = loop.run_until_complete(
                    audio_batch_tool.execute(
                        state=state,
                        shot_id=shot_id,
                        force_regenerate=force_regenerate
                    )
                )

                if result.get("success"):
                    data = result.get("data", {})
                    results.append({
                        "shot_id": shot_id,
                        "status": "success",
                        "audio_url": data.get("audio_url"),
                        "audio_results_count": len(data.get("audio_results", [])),
                        "audio_historys_count": data.get("audio_historys_count", 0),
                    })
                    success_count += 1
                    logger.info(f"[Agent Task] Shot {shot_id} 音频生成成功")
                else:
                    error_msg = result.get("error", "未知错误")
                    results.append({
                        "shot_id": shot_id,
                        "status": "failed",
                        "error": error_msg,
                    })
                    failed_count += 1
                    logger.error(f"[Agent Task] Shot {shot_id} 音频生成失败: {error_msg}")

            except Exception as e:
                logger.error(f"[Agent Task] Shot {shot_id} 音频生成异常: {e}")
                results.append({
                    "shot_id": shot_id,
<<<<<<< Updated upstream
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
                    "status": "failed",
                    "error": str(e),
                })
                failed_count += 1
<<<<<<< Updated upstream
<<<<<<< Updated upstream
<<<<<<< Updated upstream
        
        status = "success" if failed_count == 0 else "partial" if success_count > 0 else "failed"
        
        logger.info(f"[Agent Task] 批量音频生成完成: success={success_count}, failed={failed_count}")
        
=======
=======
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes

        loop.close()

        status = "success" if failed_count == 0 else "partial" if success_count > 0 else "failed"

        logger.info(f"[Agent Task] 批量 Shot 音频生成完成: success={success_count}, failed={failed_count}")

<<<<<<< Updated upstream
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
        return {
            "status": status,
            "results": results,
            "success_count": success_count,
            "failed_count": failed_count,
        }
<<<<<<< Updated upstream
<<<<<<< Updated upstream
<<<<<<< Updated upstream
        
    except Exception as e:
        logger.error(f"[Agent Task] 批量音频生成失败: {e}")
=======

    except Exception as e:
        logger.error(f"[Agent Task] 批量 Shot 音频生成任务失败: {e}")
>>>>>>> Stashed changes
=======

    except Exception as e:
        logger.error(f"[Agent Task] 批量 Shot 音频生成任务失败: {e}")
>>>>>>> Stashed changes
=======

    except Exception as e:
        logger.error(f"[Agent Task] 批量 Shot 音频生成任务失败: {e}")
>>>>>>> Stashed changes
        return {
            "status": "failed",
            "error": str(e),
            "results": [],
            "success_count": 0,
<<<<<<< Updated upstream
<<<<<<< Updated upstream
<<<<<<< Updated upstream
            "failed_count": len(audio_items),
=======
            "failed_count": len(shot_ids),
>>>>>>> Stashed changes
=======
            "failed_count": len(shot_ids),
>>>>>>> Stashed changes
=======
            "failed_count": len(shot_ids),
>>>>>>> Stashed changes
        }
