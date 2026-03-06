"""
漫剧视频导出任务 - 合并音频和视频并上传到US3
"""
import os
import tempfile
import shutil
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.core.celery_app import celery_app
from app.core.logger import logger
from app.db.base import _get_sync_session_factory
from app.models.creation import Creation
from app.models.shot import Shot
from app.utils.ffmpeg_utils import FFmpegUtils
from app.utils.us3 import US3Client, download_file_smart
from app.core.config import settings


@celery_app.task(bind=True)
def export_comic_drama_video_task(self, creation_uuid: str):
    """
    漫剧视频导出任务 - 将分镜视频和音频合并后导出

    处理步骤:
    1. 加载所有分镜的视频和音频
    2. 下载素材到临时目录
    3. 对每个分镜：合并音频和视频
    4. 拼接所有分镜视频
    5. 上传到US3
    6. 更新 creation.video_url
    """
    db: Session = _get_sync_session_factory()()
    temp_dir: Optional[str] = None

    try:
        self.update_state(state='PROGRESS', meta={'percent': 0, 'status': '开始导出'})

        # 1. 加载 creation
        creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
        if not creation:
            raise ValueError(f"未找到创作: {creation_uuid}")

        # 2. 加载所有分镜
        shots = db.query(Shot).filter(
            Shot.creation_id == creation.creation_id,
            Shot.video_url.isnot(None)
        ).order_by(Shot.shot_number).all()

        if not shots:
            raise ValueError("没有可导出的视频")

        shots_with_video = [shot for shot in shots if shot.video_url]
        logger.info(f"[ExportComicDrama] 找到 {len(shots_with_video)} 个分镜视频")

        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix=f'export_comic_{creation_uuid[:8]}_')
        downloads_dir = os.path.join(temp_dir, 'downloads')
        processed_dir = os.path.join(temp_dir, 'processed')
        os.makedirs(downloads_dir, exist_ok=True)
        os.makedirs(processed_dir, exist_ok=True)

        self.update_state(state='PROGRESS', meta={'percent': 10, 'status': '下载素材'})

        # 3. 下载所有视频和音频
        shot_merged_files = []  # [(local_video_path, start_time), ...]

        for i, shot in enumerate(shots_with_video):
            shot_video_path = None
            shot_audio_path = None
            shot_merged_path = None

            try:
                # 下载视频
                if shot.video_url:
                    video_ext = '.mp4'
                    video_local = os.path.join(downloads_dir, f"shot_{shot.shot_id}_video{video_ext}")
                    logger.info(f"[ExportComicDrama] 下载视频: {shot.video_url}")

                    download_result = download_file_smart(
                        url_or_key=shot.video_url,
                        save_file=video_local,
                        bucket=settings.US3_BUCKET,
                        timeout=300
                    )

                    if download_result.get('success'):
                        shot_video_path = video_local
                        logger.info(f"[ExportComicDrama] 视频下载成功: {shot_video_path}")
                    else:
                        logger.warning(f"[ExportComicDrama] 视频下载失败: {shot.video_url}")
                        continue

                # 下载音频（如果有）
                if shot.audio_url:
                    audio_ext = '.mp3'
                    audio_local = os.path.join(downloads_dir, f"shot_{shot.shot_id}_audio{audio_ext}")
                    logger.info(f"[ExportComicDrama] 下载音频: {shot.audio_url}")

                    download_result = download_file_smart(
                        url_or_key=shot.audio_url,
                        save_file=audio_local,
                        bucket=settings.US3_BUCKET,
                        timeout=300
                    )

                    if download_result.get('success'):
                        shot_audio_path = audio_local
                        logger.info(f"[ExportComicDrama] 音频下载成功: {shot_audio_path}")
                    else:
                        logger.warning(f"[ExportComicDrama] 音频下载失败: {shot.audio_url}")

                # 合并视频和音频
                if shot_video_path:
                    if shot_audio_path:
                        # 需要合并音频
                        shot_merged_path = os.path.join(processed_dir, f"shot_{shot.shot_id}_merged.mp4")

                        FFmpegUtils.combine_video_audio(
                            video_path=shot_video_path,
                            audio_path=shot_audio_path,
                            output_path=shot_merged_path
                        )
                        logger.info(f"[ExportComicDrama] 音频视频合并成功: {shot_merged_path}")
                    else:
                        # 没有音频，直接使用视频
                        shot_merged_path = shot_video_path

                    shot_merged_files.append({
                        'path': shot_merged_path,
                        'shot_number': shot.shot_number
                    })

            except Exception as e:
                logger.error(f"[ExportComicDrama] 处理分镜 {shot.shot_id} 失败: {str(e)}")
                continue

        if not shot_merged_files:
            raise ValueError("没有可用的分镜视频")

        self.update_state(state='PROGRESS', meta={'percent': 60, 'status': '拼接视频'})

        # 4. 拼接所有分镜视频
        if len(shot_merged_files) == 1:
            final_video_path = shot_merged_files[0]['path']
        else:
            # 按分镜编号排序
            shot_merged_files.sort(key=lambda x: x['shot_number'])

            output_filename = f"comic_drama_{uuid.uuid4().hex[:8]}.mp4"
            final_video_path = os.path.join(temp_dir, output_filename)

            list_file = os.path.join(temp_dir, "input_list.txt")
            with open(list_file, "w") as f:
                for item in shot_merged_files:
                    f.write(f"file '{item['path']}'\n")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",
                final_video_path
            ]

            logger.info(f"[ExportComicDrama] 执行拼接命令: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                logger.error(f"[ExportComicDrama] 拼接失败: {result.stderr}")
                # 降级使用第一个视频
                final_video_path = shot_merged_files[0]['path']

            logger.info(f"[ExportComicDrama] 拼接完成: {final_video_path}")

        # 5. 上传到 US3
        self.update_state(state='PROGRESS', meta={'percent': 85, 'status': '上传视频'})

        timestamp = int(datetime.utcnow().timestamp())
        put_key = f"comic_drama/{creation_uuid}/{timestamp}.mp4"

        us3_client = US3Client()
        upload_result = us3_client.upload_file(
            local_file=final_video_path,
            bucket=settings.US3_BUCKET,
            put_key=put_key
        )

        if not upload_result.get('success'):
            raise ValueError(f"上传失败: {upload_result.get('message')}")

        video_url = us3_client.get_file_url(put_key)
        logger.info(f"[ExportComicDrama] 上传完成: {video_url}")

        # 6. 更新 creation.video_url
        creation.video_url = video_url
        db.commit()

        logger.info(f"[ExportComicDrama] 导出任务完成: creation_uuid={creation_uuid}, video_url={video_url}")

        self.update_state(
            state='SUCCESS',
            meta={
                'percent': 100,
                'status': '导出完成',
                'video_url': video_url
            }
        )

        return {
            'success': True,
            'video_url': video_url,
            'creation_uuid': creation_uuid
        }

    except Exception as e:
        logger.error(f"[ExportComicDrama] 导出失败: {str(e)}", exc_info=True)

        self.update_state(
            state='FAILURE',
            meta={'percent': 0, 'status': f'导出失败: {str(e)}'}
        )
        raise

    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"[ExportComicDrama] 临时目录清理完成: {temp_dir}")
            except Exception as e:
                logger.error(f"[ExportComicDrama] 清理临时目录失败: {str(e)}")

        db.close()


import subprocess
