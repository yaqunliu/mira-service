"""
Vocab 视频生成 Celery 任务 - 单个分镜生成
"""
import os
import tempfile
import uuid
from typing import List

from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.logger import logger
from app.db.base import _get_sync_session_factory
from app.models.shot import Shot
from app.models.creation import Creation
from app.utils.us3 import US3Client
from app.utils.ai_client import AIClient
from app.core.config import settings


def download_video(url: str, temp_dir: str, model: str = None) -> str:
    """下载视频到临时目录"""
    import urllib.request
    
    ext = os.path.splitext(url.split("?")[0])[1] or ".mp4"
    filename = f"video_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(temp_dir, filename)
    
    if model == "sora-2":
        from app.utils.ai_client import AIClient
        ai_client = AIClient()
        headers = {
            "Authorization": ai_client.sora2_api_key
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            with open(filepath, 'wb') as f:
                f.write(response.read())
    else:
        urllib.request.urlretrieve(url, filepath)
    
    return filepath


@celery_app.task(bind=True)
def generate_single_vocab_video_task(self, shot_id: int, model: str = "viduq2"):
    """
    单个分镜视频生成任务
    
    Args:
        shot_id: 分镜ID
        model: 视频模型
    """
    db: Session = _get_sync_session_factory()()
    ai_client = AIClient()
    us3_client = US3Client()
    
    try:
        shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
        
        if not shot:
            raise ValueError(f"未找到分镜: {shot_id}")
        
        logger.info(f"[VocabVideoGen] 开始生成视频: shot_id={shot_id}, model={model}")
        
        self.update_state(
            state='PROGRESS',
            meta={
                'percent': 0,
                'status': '开始生成视频',
                'shot_id': shot_id
            }
        )
        
        extra_data = shot.extra_data or {}
        video_prompt = extra_data.get("video_prompt", "")
        reference_images = extra_data.get("reference_images", [])
        audio_text = extra_data.get("audio_text", "")
        duration = extra_data.get("duration", 4)
        
        logger.info(f"[VocabVideoGen] 生成视频: shot_id={shot_id}, prompt={video_prompt[:100]}...")
        logger.info(f"[VocabVideoGen] 参考图: {reference_images}")
        
        video_url = ""
        error_msg = ""
        
        if settings.DEBUG_GENERATE_VIDEO:
            video_url = settings.DEBUG_GENERATE_VIDEO_URL
            logger.info(f"[VocabVideoGen] DEBUG模式，使用固定URL: {video_url}")
        else:
            temp_video_path = None
            temp_dir = None
            
            try:
                if model == "sora-2":
                    temp_url = ai_client.generate_video_by_prompt_sora2(
                        prompt=video_prompt,
                        model="sora-2",
                        duration=duration,
                        size="1280x720"
                    )
                elif model.startswith("vidu") and reference_images:
                    ref_urls = [ref.get("url", "") for ref in reference_images if ref.get("url")]
                    image_url = ",".join(ref_urls)
                    
                    temp_url = ai_client.generate_video_by_reference_vidu(
                        image_url=image_url,
                        prompt=video_prompt,
                        model=model,
                        duration=duration,
                        aspect_ratio="16:9",
                        resolution="720p",
                        audio=True
                    )
                elif model.startswith("vidu"):
                    temp_url = ai_client.generate_video_by_prompt_vidu(
                        prompt=video_prompt,
                        model=model,
                        duration=duration,
                        aspect_ratio="16:9",
                        resolution="720p"
                    )
                else:
                    temp_url = ai_client.generate_video_by_prompt_doubao_modelverse(
                        prompt=video_prompt,
                        duration=duration,
                        aspect_ratio="16:9",
                        resolution="720p"
                    )
                
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'percent': 50,
                        'status': '下载视频',
                        'shot_id': shot_id
                    }
                )
                
                logger.info(f"[VocabVideoGen] 视频生成完成，下载临时URL: {temp_url}")
                
                temp_dir = tempfile.mkdtemp(prefix="vocab_video_")
                temp_video_path = download_video(temp_url, temp_dir, model)
                logger.info(f"[VocabVideoGen] 视频下载完成: {temp_video_path}")
                
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'percent': 80,
                        'status': '上传视频',
                        'shot_id': shot_id
                    }
                )
                
                creation = db.query(Creation).filter(Creation.creation_id == shot.creation_id).first()
                owner_id = creation.owner_id if creation else 1
                
                put_key = f"vocab/{owner_id}/{uuid.uuid4().hex[:8]}.mp4"
                upload_result = us3_client.upload_file(
                    local_file=temp_video_path,
                    bucket=settings.US3_BUCKET,
                    put_key=put_key
                )
                
                if upload_result.get("success"):
                    video_url = us3_client.get_file_url(put_key, settings.US3_BUCKET)
                    logger.info(f"[VocabVideoGen] 视频上传成功: {video_url}")
                else:
                    raise ValueError(f"上传失败: {upload_result.get('message')}")
                    
            except Exception as e:
                error_msg = str(e)
                logger.error(f"[VocabVideoGen] 视频生成失败: shot_id={shot_id}, error={error_msg}")
                
                shot.status = "failed"
                shot.error_message = error_msg
                db.commit()
                
                self.update_state(
                    state='FAILURE',
                    meta={
                        'percent': 0,
                        'status': '失败',
                        'shot_id': shot_id,
                        'error': error_msg
                    }
                )
                
                if temp_video_path and os.path.exists(temp_video_path):
                    try:
                        os.remove(temp_video_path)
                    except:
                        pass
                if temp_dir and os.path.exists(temp_dir):
                    try:
                        import shutil
                        shutil.rmtree(temp_dir)
                    except:
                        pass
                
                return {
                    "success": False,
                    "shot_id": shot_id,
                    "error": error_msg
                }
        
        if video_url:
            shot.video_url = video_url
            shot.status = "completed"
            db.commit()
            logger.info(f"[VocabVideoGen] 视频生成成功: shot_id={shot_id}, url={video_url}")
            
            self.update_state(
                state='COMPLETED',
                meta={
                    'percent': 100,
                    'status': '完成',
                    'shot_id': shot_id,
                    'video_url': video_url
                }
            )
            
            return {
                "success": True,
                "shot_id": shot_id,
                "video_url": video_url
            }
        else:
            shot.status = "failed"
            shot.error_message = error_msg or "视频生成失败"
            db.commit()
            logger.error(f"[VocabVideoGen] 视频生成失败: shot_id={shot_id}")
            
            self.update_state(
                state='FAILURE',
                meta={
                    'percent': 0,
                    'status': '失败',
                    'shot_id': shot_id,
                    'error': error_msg
                }
            )
            
            return {
                "success": False,
                "shot_id": shot_id,
                "error": error_msg
            }
        
    except Exception as e:
        logger.error(f"[VocabVideoGen] 视频生成失败: shot_id={shot_id}, error={e}")
        raise
        
    finally:
        db.close()


@celery_app.task(bind=True)
def generate_vocab_videos_task(self, shot_ids: List[int], model: str = "viduq2"):
    """
    Vocab 视频生成任务 - 批量生成（保留兼容）
    
    Args:
        shot_ids: 分镜ID列表
        model: 视频模型
    """
    logger.warning("[VocabVideoGen] generate_vocab_videos_task 已弃用，请使用 generate_single_vocab_video_task")
    
    for shot_id in shot_ids:
        generate_single_vocab_video_task.delay(shot_id, model)
    
    return {
        "success": True,
        "message": f"已提交 {len(shot_ids)} 个任务"
    }
