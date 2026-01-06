"""
视频导出任务 - 从时间轴配置导出最终视频
"""
import os
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.celery_app import celery_app
from app.core.logger import logger
from app.db.session import SessionLocal
from app.models.creation import Creation
from app.utils.ffmpeg_utils import FFmpegUtils
from app.utils.us3 import US3Client, download_file_smart
from app.core.config import settings


def update_export_progress(db: Session, creation_id: int, percent: int, status: str):
    """更新导出进度到 creation.extra_data.steps.videoExport"""
    creation = db.query(Creation).filter(
        Creation.creation_id == creation_id
    ).with_for_update().first()

    if creation and creation.extra_data and 'steps' in creation.extra_data:
        if 'videoExport' in creation.extra_data['steps']:
            creation.extra_data['steps']['videoExport']['progress'] = {
                'percent': percent,
                'status': status
            }
            creation.extra_data['steps']['videoExport']['updatedAt'] = int(datetime.utcnow().timestamp())
            flag_modified(creation, 'extra_data')
            db.commit()


@celery_app.task(bind=True)
def export_video_task(self, creation_id: int, user_id: int):
    """
    导出视频任务

    Args:
        creation_id: 创作ID
        user_id: 用户ID

    处理步骤:
    1. 加载creation和timeline_config
    2. 下载所有clips到临时目录
    3. 处理视频轨道（裁剪、透明度、可见性）
    4. 处理音频轨道（裁剪、音量、静音）
    5. 生成SRT字幕文件并转换为ASS（带样式）
    6. 合并所有轨道
    7. 上传到US3
    8. 更新creation.extra_data.outputs
    9. 更新creation.status为completed
    10. 清理临时文件
    """
    db: Session = SessionLocal()
    temp_dir: Optional[str] = None

    try:
        # 更新任务状态：开始
        self.update_state(state='PROGRESS', meta={'percent': 0, 'status': '任务开始'})

        # 1. 加载creation（带行锁）
        creation = db.query(Creation).filter(
            Creation.creation_id == creation_id,
            Creation.owner_id == user_id
        ).with_for_update().first()

        if not creation:
            raise ValueError(f"未找到creation: {creation_id}")

        # 初始化 extra_data 和 steps
        if not creation.extra_data:
            creation.extra_data = {}
        if 'steps' not in creation.extra_data:
            creation.extra_data['steps'] = {}

        # 更新 videoExport step 状态为 processing
        creation.extra_data['steps']['videoExport'] = {
            'status': 'processing',
            'triggered': True,
            'taskId': self.request.id,
            'updatedAt': int(datetime.utcnow().timestamp()),
            'progress': {
                'percent': 0,
                'status': '任务开始'
            }
        }
        flag_modified(creation, 'extra_data')
        db.commit()

        if not creation.timeline_config:
            raise ValueError("timeline_config为空，无法导出")

        timeline_config = creation.timeline_config
        project_duration = timeline_config.get('duration', 0)
        fps = timeline_config.get('fps', 30)
        tracks = timeline_config.get('tracks', [])

        if project_duration <= 0:
            raise ValueError("项目时长无效")

        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix=f'export_{creation.uuid}_')
        downloads_dir = os.path.join(temp_dir, 'downloads')
        processed_dir = os.path.join(temp_dir, 'processed')
        output_dir = os.path.join(temp_dir, 'output')

        os.makedirs(downloads_dir, exist_ok=True)
        os.makedirs(processed_dir, exist_ok=True)
        os.makedirs(output_dir, exist_ok=True)

        logger.info(f"导出任务开始: creation_id={creation_id}, temp_dir={temp_dir}")

        # 2. 下载所有clips
        self.update_state(state='PROGRESS', meta={'percent': 10, 'status': '下载素材文件'})
        update_export_progress(db, creation_id, 10, '下载素材文件')

        clip_files = {}  # {clip_id: local_path}

        for track in tracks:
            track_type = track.get('type')
            clips = track.get('clips', [])

            for clip in clips:
                clip_id = clip.get('id')
                clip_url = clip.get('url')

                if not clip_url or clip_id in clip_files:
                    continue

                # 跳过文本轨道的下载
                if track_type == 'text':
                    continue

                # 确定文件扩展名
                if track_type == 'video':
                    ext = '.mp4'
                elif track_type == 'audio':
                    ext = '.mp3'
                else:
                    ext = '.tmp'

                local_path = os.path.join(downloads_dir, f"{clip_id}{ext}")

                try:
                    # 使用智能下载（支持US3和HTTP）
                    download_result = download_file_smart(
                        url_or_key=clip_url,
                        save_file=local_path,
                        bucket=settings.US3_BUCKET,
                        timeout=300
                    )

                    if download_result.get('success'):
                        clip_files[clip_id] = local_path
                        logger.info(f"下载成功: {clip_id} -> {local_path}")
                    else:
                        logger.warning(f"下载失败: {clip_id}, {download_result.get('message')}")
                except Exception as e:
                    logger.error(f"下载clip失败: {clip_id}, {str(e)}")

        # 3. 处理视频轨道
        self.update_state(state='PROGRESS', meta={'percent': 30, 'status': '处理视频轨道'})
        update_export_progress(db, creation_id, 30, '处理视频轨道')

        video_tracks = [t for t in tracks if t.get('type') == 'video']
        processed_video_clips = []

        for track in video_tracks:
            clips = track.get('clips', [])

            for clip in clips:
                clip_id = clip.get('id')
                if clip_id not in clip_files:
                    continue

                # 检查可见性
                if not clip.get('isVisible', True):
                    continue

                source_start = clip.get('sourceStart', 0)
                source_end = clip.get('sourceEnd', clip.get('duration', 0))
                start_in_timeline = clip.get('startInTimeline', 0)
                opacity = clip.get('opacity', 1.0)

                # 裁剪视频
                trimmed_path = os.path.join(processed_dir, f"{clip_id}_trimmed.mp4")

                try:
                    FFmpegUtils.trim_video_clip(
                        input_path=clip_files[clip_id],
                        output_path=trimmed_path,
                        start=source_start,
                        end=source_end,
                        apply_opacity=opacity
                    )

                    processed_video_clips.append({
                        'path': trimmed_path,
                        'startInTimeline': start_in_timeline,
                        'duration': source_end - source_start
                    })
                except Exception as e:
                    logger.error(f"处理视频clip失败: {clip_id}, {str(e)}")

        # 4. 处理音频轨道
        self.update_state(state='PROGRESS', meta={'percent': 50, 'status': '处理音频轨道'})
        update_export_progress(db, creation_id, 50, '处理音频轨道')

        audio_tracks = [t for t in tracks if t.get('type') == 'audio']
        processed_audio_clips = []

        for track in audio_tracks:
            clips = track.get('clips', [])

            for clip in clips:
                clip_id = clip.get('id')
                if clip_id not in clip_files:
                    continue

                # 检查是否静音
                if clip.get('isMuted', False):
                    continue

                source_start = clip.get('sourceStart', 0)
                source_end = clip.get('sourceEnd', clip.get('duration', 0))
                start_in_timeline = clip.get('startInTimeline', 0)
                volume = clip.get('volume', 1.0)

                # 裁剪音频
                trimmed_path = os.path.join(processed_dir, f"{clip_id}_trimmed.mp3")

                try:
                    FFmpegUtils.trim_audio_clip(
                        input_path=clip_files[clip_id],
                        output_path=trimmed_path,
                        start=source_start,
                        end=source_end,
                        volume=volume
                    )

                    processed_audio_clips.append({
                        'path': trimmed_path,
                        'startInTimeline': start_in_timeline,
                        'duration': source_end - source_start,
                        'volume': volume
                    })
                except Exception as e:
                    logger.error(f"处理音频clip失败: {clip_id}, {str(e)}")

        # 5. 生成字幕
        self.update_state(state='PROGRESS', meta={'percent': 60, 'status': '生成字幕'})
        update_export_progress(db, creation_id, 60, '生成字幕')

        text_tracks = [t for t in tracks if t.get('type') == 'text']
        subtitle_path = None
        ass_subtitle_path = None

        if text_tracks:
            text_clips = []
            for track in text_tracks:
                for clip in track.get('clips', []):
                    text = clip.get('text', '').strip()
                    if text:
                        text_clips.append({
                            'text': text,
                            'startInTimeline': clip.get('startInTimeline', 0),
                            'duration': clip.get('duration', 0)
                        })

            if text_clips:
                srt_path = os.path.join(processed_dir, 'subtitles.srt')
                ass_subtitle_path = os.path.join(processed_dir, 'subtitles.ass')

                try:
                    # 生成SRT
                    FFmpegUtils.generate_srt_file(text_clips, srt_path)

                    # 转换为ASS（带样式）
                    FFmpegUtils.convert_srt_to_ass(srt_path, ass_subtitle_path)

                    logger.info(f"字幕生成成功: {ass_subtitle_path}")
                except Exception as e:
                    logger.error(f"生成字幕失败: {str(e)}")
                    ass_subtitle_path = None

        # 6. 合并轨道
        self.update_state(state='PROGRESS', meta={'percent': 70, 'status': '合并视频'})
        update_export_progress(db, creation_id, 70, '合并视频')

        # 6.1 合并视频轨道
        merged_video_path = os.path.join(output_dir, 'merged_video.mp4')

        if not processed_video_clips:
            raise ValueError("没有可用的视频片段")

        if len(processed_video_clips) == 1 and processed_video_clips[0]['startInTimeline'] == 0:
            # 单个视频片段且从0开始，直接使用
            merged_video_path = processed_video_clips[0]['path']
        else:
            # 多个片段，需要合并
            FFmpegUtils.concat_videos_with_timeline(
                clips_info=processed_video_clips,
                output_path=merged_video_path,
                total_duration=project_duration
            )

        # 6.2 合并音频轨道（如果有音频）
        video_with_audio_path = merged_video_path

        if processed_audio_clips:
            merged_audio_path = os.path.join(output_dir, 'merged_audio.mp3')

            FFmpegUtils.concat_audios_with_timeline(
                clips_info=processed_audio_clips,
                output_path=merged_audio_path,
                total_duration=project_duration
            )

            # 6.3 合并视频和音频
            video_with_audio_path = os.path.join(output_dir, 'video_with_audio.mp4')

            FFmpegUtils.combine_video_audio(
                video_path=merged_video_path,
                audio_path=merged_audio_path,
                output_path=video_with_audio_path
            )
        else:
            logger.info("没有音频轨道，跳过音频合并")

        # 6.4 烧录字幕（如果有）
        if ass_subtitle_path and os.path.exists(ass_subtitle_path):
            final_video_path = os.path.join(output_dir, 'final_video.mp4')

            FFmpegUtils.burn_subtitles(
                video_path=video_with_audio_path,
                subtitle_path=ass_subtitle_path,
                output_path=final_video_path
            )
        else:
            final_video_path = video_with_audio_path

        # 获取视频信息
        video_info = FFmpegUtils.get_video_info(final_video_path)
        file_size = os.path.getsize(final_video_path)

        # 7. 上传到US3
        self.update_state(state='PROGRESS', meta={'percent': 90, 'status': '上传视频'})
        update_export_progress(db, creation_id, 90, '上传视频')

        timestamp = int(datetime.utcnow().timestamp())
        put_key = f"exports/{creation.uuid}/{timestamp}.mp4"

        us3_client = US3Client()
        us3_client.upload_file(
            local_file=final_video_path,
            bucket=settings.US3_BUCKET,
            put_key=put_key
        )

        video_url = us3_client.get_file_url(put_key)

        logger.info(f"视频上传成功: {video_url}")

        # 8. 更新creation.extra_data.outputs
        if not creation.extra_data:
            creation.extra_data = {}

        if "outputs" not in creation.extra_data:
            creation.extra_data["outputs"] = []

        export_record = {
            "video_url": video_url,
            "export_at": datetime.utcnow().isoformat(),
            "duration": video_info.get('duration', project_duration),
            "resolution": f"{video_info.get('width', 1920)}x{video_info.get('height', 1080)}",
            "file_size": file_size,
            "status": "completed"
        }

        creation.extra_data["outputs"].append(export_record)
        flag_modified(creation, "extra_data")

        # 9. 更新status为completed（如果这是第一次导出）
        if creation.status != "completed":
            creation.status = "completed"

        # 更新 videoExport step 状态为 success
        creation.extra_data['steps']['videoExport'] = {
            'status': 'success',
            'triggered': True,
            'taskId': self.request.id,
            'updatedAt': int(datetime.utcnow().timestamp()),
            'progress': {
                'percent': 100,
                'status': '导出完成'
            },
            'result': {
                'video_url': video_url,
                'file_size': file_size
            }
        }
        flag_modified(creation, 'extra_data')
        db.commit()

        logger.info(f"导出任务完成: creation_id={creation_id}, video_url={video_url}")

        # 10. 更新任务状态：完成
        self.update_state(
            state='SUCCESS',
            meta={
                'percent': 100,
                'status': '导出完成',
                'video_url': video_url,
                'file_size': file_size
            }
        )

        return {
            'success': True,
            'video_url': video_url,
            'file_size': file_size,
            'creation_id': creation_id
        }

    except Exception as e:
        logger.error(f"导出任务失败: creation_id={creation_id}, error={str(e)}")

        # 记录失败信息到extra_data
        try:
            creation = db.query(Creation).filter(
                Creation.creation_id == creation_id
            ).with_for_update().first()

            if creation:
                if not creation.extra_data:
                    creation.extra_data = {}

                if "outputs" not in creation.extra_data:
                    creation.extra_data["outputs"] = []

                export_record = {
                    "video_url": None,
                    "export_at": datetime.utcnow().isoformat(),
                    "status": "failed",
                    "error": str(e),
                    "error_type": type(e).__name__
                }

                creation.extra_data["outputs"].append(export_record)

                # 更新 videoExport step 状态为 failed
                if 'steps' not in creation.extra_data:
                    creation.extra_data['steps'] = {}
                creation.extra_data['steps']['videoExport'] = {
                    'status': 'failed',
                    'triggered': True,
                    'updatedAt': int(datetime.utcnow().timestamp()),
                    'error': str(e)
                }

                flag_modified(creation, "extra_data")
                db.commit()
        except Exception as commit_error:
            logger.error(f"保存失败记录时出错: {str(commit_error)}")

        # 更新任务状态：失败
        self.update_state(
            state='FAILURE',
            meta={'percent': 0, 'status': f'导出失败: {str(e)}'}
        )

        raise

    finally:
        # 11. 清理临时文件
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
                logger.info(f"临时目录清理完成: {temp_dir}")
            except Exception as e:
                logger.error(f"清理临时目录失败: {str(e)}")

        db.close()
