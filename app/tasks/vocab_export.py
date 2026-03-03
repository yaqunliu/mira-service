"""
Vocab 视频导出任务 - 拼接多个分镜视频并添加转场
"""
import os
import subprocess
import tempfile
import uuid

from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.logger import logger
from app.db.base import _get_sync_session_factory
from app.models.shot import Shot
from app.models.creation import Creation
from app.utils.us3 import US3Client
from app.core.config import settings



@celery_app.task(bind=True)
def export_vocab_video_task(self, creation_id: int, user_id: int, shot_ids: list, task_uuid: str = None):
    """
    Vocab 视频导出任务 - 拼接视频并添加转场效果
    
    Args:
        creation_id: 创作ID
        user_id: 用户ID
        shot_ids: 分镜ID列表
        task_uuid: VocabTask UUID（用于更新任务状态）
    """
    db: Session = _get_sync_session_factory()()
    temp_dir = None

    try:
        self.update_state(state='PROGRESS', meta={'percent': 0, 'status': '开始导出'})

        # 1. 加载分镜（只查询当前 creation 的分镜）
        shots = db.query(Shot).filter(
            Shot.shot_id.in_(shot_ids),
            Shot.creation_id == creation_id
        ).all()
        
        video_urls = []
        for shot in shots:
            if shot.video_url:
                video_urls.append(shot.video_url)
        
        if not video_urls:
            raise ValueError("没有可导出的视频")

        logger.info(f"[ExportVocab] 开始导出 {len(video_urls)} 个视频")

        # 2. 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="vocab_export_")
        
        # 3. 下载所有视频
        downloaded_files = []
        for i, url in enumerate(video_urls):
            self.update_state(state='PROGRESS', meta={
                'percent': int(20 + (i / len(video_urls) * 30)),
                'status': f'下载视频 {i+1}/{len(video_urls)}'
            })
            
            filepath = os.path.join(temp_dir, f"video_{i}.mp4")
            
            import urllib.request
            if "sora" in url or "modelverse" in url:
                from app.utils.ai_client import AIClient
                ai_client = AIClient()
                headers = {"Authorization": ai_client.sora2_api_key}
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req) as response:
                    with open(filepath, 'wb') as f:
                        f.write(response.read())
            else:
                urllib.request.urlretrieve(url, filepath)
            
            downloaded_files.append(filepath)
            logger.info(f"[ExportVocab] 下载完成: {filepath}")

        if len(downloaded_files) == 1:
            final_video_path = downloaded_files[0]
        else:
            # 4. 用 ffmpeg 直接拼接视频（不加转场）
            self.update_state(state='PROGRESS', meta={'percent': 60, 'status': '拼接视频'})
            
            output_filename = f"vocab_{uuid.uuid4().hex[:8]}.mp4"
            final_video_path = os.path.join(temp_dir, output_filename)
            
            # 构建 ffmpeg 命令，直接拼接视频
            list_file = os.path.join(temp_dir, "input_list.txt")
            with open(list_file, "w") as f:
                for filepath in downloaded_files:
                    f.write(f"file '{filepath}'\n")
            
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                final_video_path
            ]
            
            logger.info(f"[ExportVocab] 执行 ffmpeg 命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            
            if result.returncode != 0:
                logger.error(f"[ExportVocab] ffmpeg 拼接失败: {result.stderr}")
                final_video_path = downloaded_files[0]
            
            logger.info(f"[ExportVocab] 拼接完成: {final_video_path}")

        # 5. 上传到 US3
        self.update_state(state='PROGRESS', meta={'percent': 85, 'status': '上传视频'})
        
        us3 = US3Client()
        result = us3.upload_file(
            local_file=final_video_path,
            bucket=settings.US3_BUCKET,
            put_key=f"vocab/{user_id}/{os.path.basename(final_video_path)}"
        )
        
        if result.get("success"):
            video_url = us3.get_file_url(result["key"], settings.US3_BUCKET)
        else:
            raise ValueError(f"上传失败: {result.get('message')}")
        
        logger.info(f"[ExportVocab] 上传完成: {video_url}")

        # 6. 更新 creation
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if creation:
            creation.video_url = video_url
            creation.status = "completed"
            db.commit()

        self.update_state(state='COMPLETED', meta={'percent': 100, 'status': '完成', 'video_url': video_url})
        
        return {
            "success": True,
            "video_url": video_url
        }
        
    except Exception as e:
        logger.error(f"[ExportVocab] 导出失败: {e}", exc_info=True)
        
        self.update_state(state='FAILURE', meta={'error': str(e)})
        raise
        
    finally:
        # 清理临时目录
        if temp_dir and os.path.exists(temp_dir):
            try:
                import shutil
                shutil.rmtree(temp_dir)
            except:
                pass
        db.close()
