"""
音频生成任务
使用 Fish Audio TTS 为分镜生成旁白音频
包含：单个分镜音频生成、批量音频生成、音频合并、字幕生成
"""
import os
import uuid
import tempfile
import subprocess
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pydub import AudioSegment

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from sqlalchemy.orm import Session, selectinload
from app.models.creation import Creation
from app.models.scene import Scene
from app.models.shot import Shot
from app.schemas.creation import CreationStatus
from app.core.exceptions import NotFoundError, BaseServiceException
from app.utils.task_types import TaskType
from app.utils.fish_audio import get_fish_audio_client
from app.core.logger import logger
from app.utils.us3 import US3Client


def _get_audio_duration_ms(audio_bytes: bytes) -> int:
    """
    获取音频时长（毫秒）
    
    Args:
        audio_bytes: 音频数据
        
    Returns:
        时长（毫秒）
    """
    tmp_path = None
    try:
        # 保存到临时文件
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        
        # 使用 pydub 读取时长
        audio = AudioSegment.from_mp3(tmp_path)
        duration_ms = len(audio)
        
        return duration_ms
    except Exception as e:
        logger.warning(f"获取音频时长失败: {e}")
        return 0
    finally:
        # 清理临时文件
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass


def _format_srt_time(ms: int) -> str:
    """
    将毫秒转换为 SRT 时间格式
    
    Args:
        ms: 毫秒数
        
    Returns:
        SRT 格式时间字符串 (HH:MM:SS,mmm)
    """
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    milliseconds = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _generate_srt_content(shots_data: List[Dict[str, Any]]) -> str:
    """
    生成 SRT 字幕内容
    
    Args:
        shots_data: 分镜数据列表，每个包含 narration, start_time, end_time
        
    Returns:
        SRT 格式字幕内容
    """
    srt_lines = []
    for idx, shot in enumerate(shots_data, 1):
        start_time = _format_srt_time(shot["start_time"])
        end_time = _format_srt_time(shot["end_time"])
        text = shot.get("narration", "").strip()
        
        if text:
            srt_lines.append(f"{idx}")
            srt_lines.append(f"{start_time} --> {end_time}")
            srt_lines.append(text)
            srt_lines.append("")  # 空行分隔
    
    return "\n".join(srt_lines)


def _generate_single_shot_audio(shot_id: int, creation_id: int, voice_id: str, voice_speed: float = 1.0) -> dict:
    """
    生成单个分镜的音频（线程安全函数）
    
    Args:
        shot_id: 分镜ID
        creation_id: 创作ID（用于生成存储路径）
        voice_id: 语音模型ID
        voice_speed: 语速设置，范围 0-10，默认 1.0
        
    Returns:
        包含分镜ID、音频URL、时长等信息的字典
    """
    db: Session = SessionLocal()
    temp_file_path = None
    try:
        shot = (
            db.query(Shot)
            .options(selectinload(Shot.scene))
            .filter(Shot.shot_id == shot_id)
            .first()
        )
        if not shot:
            raise NotFoundError(detail=f"分镜不存在: shot_id={shot_id}")
        
        # 检查是否有旁白文本
        if not shot.narration:
            logger.warning(f"分镜 {shot_id} 没有旁白文本，跳过生成")
            return {
                "shot_id": shot_id,
                "shot_title": shot.title,
                "shot_number": shot.shot_number,
                "scene_id": shot.scene_id,
                "success": False,
                "error": "没有旁白文本",
                "narration": None,
                "skipped": True
            }
        
        logger.info(f"开始为分镜 {shot_id} 生成音频，旁白长度: {len(shot.narration)}")
        
        # 调用 Fish Audio TTS
        fish_client = get_fish_audio_client()
        # 将 voice_speed 转换为 Fish Audio 的 speed 参数
        # Fish Audio 的 speed 范围通常是 0.5-2.0，我们需要将 0-10 映射到这个范围
        # 假设 1.0 对应正常语速，0 对应最慢（0.5），10 对应最快（2.0）
        # 线性映射：speed = 0.5 + (voice_speed / 10) * 1.5
        fish_speed = 0.5 + (voice_speed / 10.0) * 1.5
        audio_bytes = fish_client.text_to_speech_bytes(
            text=shot.narration,
            reference_id=voice_id,
            format="mp3",
            speed=fish_speed
        )
        
        # 获取音频时长
        duration_ms = _get_audio_duration_ms(audio_bytes)
        logger.info(f"分镜 {shot_id} 音频时长: {duration_ms}ms")
        
        # 保存到临时文件
        audio_extension = ".mp3"
        temp_fd, temp_file_path = tempfile.mkstemp(suffix=audio_extension)
        try:
            with os.fdopen(temp_fd, 'wb') as tmp_file:
                tmp_file.write(audio_bytes)
        except Exception as e:
            os.close(temp_fd)
            raise
        
        # 上传到 US3
        audio_uuid = str(uuid.uuid4())
        put_key = f"creations/{creation_id}/shots/{shot_id}/audio_{audio_uuid}{audio_extension}"
        
        us3_client = US3Client()
        upload_result = us3_client.upload_file(
            local_file=temp_file_path,
            bucket=None,
            put_key=put_key
        )
        
        if not upload_result['success']:
            raise Exception(f"音频上传 US3 失败: {upload_result.get('message')}")
        
        audio_url = us3_client.get_file_url(put_key)
        logger.info(f"音频上传成功: {audio_url}")
        
        # 更新分镜信息
        shot.audio_url = audio_url
        shot.audio_duration = duration_ms
        db.commit()
        db.refresh(shot)
        
        return {
            "shot_id": shot_id,
            "shot_title": shot.title,
            "shot_number": shot.shot_number,
            "scene_id": shot.scene_id,
            "success": True,
            "audio_url": audio_url,
            "duration_ms": duration_ms,
            "narration": shot.narration,
            "audio_bytes": audio_bytes  # 用于后续合并
        }
        
    except Exception as e:
        logger.error(f"分镜 {shot_id} 音频生成失败: {str(e)}", exc_info=True)
        db.rollback()
        scene_id = 0
        shot_number = 0
        # 尝试从数据库获取 scene_id 和 shot_number
        try:
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                scene_id = shot.scene_id
                shot_number = shot.shot_number
        except:
            pass
        return {
            "shot_id": shot_id,
            "shot_number": shot_number,
            "scene_id": scene_id,
            "success": False,
            "error": str(e)
        }
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception:
                pass
        db.close()


def _merge_audio_files(audio_results: List[Dict], creation_id: int) -> Optional[str]:
    """
    合并多个音频文件
    
    Args:
        audio_results: 音频生成结果列表
        creation_id: 创作ID
        
    Returns:
        合并后的音频URL，失败返回None
    """
    temp_files = []
    merged_path = None
    
    try:
        # 按 (scene_id, shot_number) 排序
        sorted_results = sorted(
            [r for r in audio_results if r.get("success") and r.get("audio_bytes")],
            key=lambda x: (x.get("scene_id", 0), x.get("shot_number", 0))
        )
        
        if not sorted_results:
            logger.warning("没有可合并的音频")
            return None
        
        # 合并音频
        combined = AudioSegment.empty()
        for result in sorted_results:
            audio_bytes = result.get("audio_bytes")
            if audio_bytes:
                # 保存到临时文件
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp.write(audio_bytes)
                    temp_files.append(tmp.name)
                
                # 加载并合并
                segment = AudioSegment.from_mp3(temp_files[-1])
                combined += segment
        
        if len(combined) == 0:
            return None
        
        # 导出合并后的音频
        merged_fd, merged_path = tempfile.mkstemp(suffix=".mp3")
        os.close(merged_fd)
        combined.export(merged_path, format="mp3", bitrate="128k")
        
        # 上传到 US3
        audio_uuid = str(uuid.uuid4())
        put_key = f"creations/{creation_id}/merged_audio_{audio_uuid}.mp3"
        
        us3_client = US3Client()
        upload_result = us3_client.upload_file(
            local_file=merged_path,
            bucket=None,
            put_key=put_key
        )
        
        if not upload_result['success']:
            raise Exception(f"合并音频上传失败: {upload_result.get('message')}")
        
        audio_url = us3_client.get_file_url(put_key)
        logger.info(f"合并音频上传成功: {audio_url}")
        return audio_url
        
    except Exception as e:
        logger.error(f"音频合并失败: {e}", exc_info=True)
        return None
    finally:
        # 清理临时文件
        for tmp_path in temp_files:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
        if merged_path and os.path.exists(merged_path):
            try:
                os.remove(merged_path)
            except Exception:
                pass


def _generate_and_upload_srt(audio_results: List[Dict], creation_id: int) -> Optional[str]:
    """
    生成并上传 SRT 字幕文件
    
    Args:
        audio_results: 音频生成结果列表
        creation_id: 创作ID
        
    Returns:
        字幕文件URL，失败返回None
    """
    temp_path = None
    try:
        # 按 (scene_id, shot_number) 排序
        sorted_results = sorted(
            [r for r in audio_results if r.get("success") and r.get("duration_ms")],
            key=lambda x: (x.get("scene_id", 0), x.get("shot_number", 0))
        )
        
        if not sorted_results:
            return None
        
        # 计算每个分镜的开始和结束时间
        current_time = 0
        shots_with_time = []
        for result in sorted_results:
            duration = result.get("duration_ms", 0)
            shots_with_time.append({
                "narration": result.get("narration", ""),
                "start_time": current_time,
                "end_time": current_time + duration,
            })
            current_time += duration
        
        # 生成 SRT 内容
        srt_content = _generate_srt_content(shots_with_time)
        
        if not srt_content.strip():
            return None
        
        # 保存到临时文件
        temp_fd, temp_path = tempfile.mkstemp(suffix=".srt")
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        
        # 上传到 US3
        srt_uuid = str(uuid.uuid4())
        put_key = f"creations/{creation_id}/subtitle_{srt_uuid}.srt"
        
        us3_client = US3Client()
        upload_result = us3_client.upload_file(
            local_file=temp_path,
            bucket=None,
            put_key=put_key
        )
        
        if not upload_result['success']:
            raise Exception(f"字幕上传失败: {upload_result.get('message')}")
        
        subtitle_url = us3_client.get_file_url(put_key)
        logger.info(f"字幕上传成功: {subtitle_url}")
        return subtitle_url
        
    except Exception as e:
        logger.error(f"字幕生成失败: {e}", exc_info=True)
        return None
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


@celery_app.task(bind=True, name="generate_single_shot_audio_task")
def generate_single_shot_audio_task(self, shot_id: int, creation_id: int, voice_id: str, voice_speed: float = 1.0) -> dict:
    """
    Celery任务：生成单个分镜的音频
    """
    logger.info(f"开始执行分镜音频生成任务: shot_id={shot_id}, voice_speed={voice_speed}")
    
    self.update_state(
        state="PROGRESS",
        meta={
            "task_type": TaskType.AUDIO_GENERATION,
            "shot_id": shot_id,
            "creation_id": creation_id,
            "status": "生成中"
        }
    )
    
    result = _generate_single_shot_audio(shot_id, creation_id, voice_id, voice_speed)
    # 移除 audio_bytes，避免序列化问题
    result.pop("audio_bytes", None)
    result["task_type"] = TaskType.AUDIO_GENERATION
    return result


@celery_app.task(bind=True, name="generate_creation_audio_task")
def generate_creation_audio_task(self, creation_id: int, voice_id: str, voice_speed: float = 1.0, force_regenerate: bool = False):
    """
    生成创作下所有分镜的音频 + 字幕（主任务）
    
    流程：
    1. 更新创作的 voice_id 和 voice_speed
    2. 并发生成所有分镜的音频
    3. 合并所有音频
    4. 生成 SRT 字幕
    5. 更新创作状态
    
    Args:
        creation_id: 创作ID
        voice_id: 语音模型ID
        voice_speed: 语速设置，范围 0-10，默认 1.0
        force_regenerate: 是否强制重新生成
        
    Returns:
        包含处理结果的字典
    """
    db: Session = SessionLocal()
    try:
        # 验证创作是否存在
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if not creation:
            raise NotFoundError(detail=f"创作不存在: creation_id={creation_id}")
        
        # 检查是否已生成音频和字幕，如果已存在且不强制重新生成，则跳过
        if not force_regenerate and creation.audio_url and creation.subtitle_url:
            logger.info(f"创作 {creation_id} 音频和字幕已存在，跳过生成")
            creation.voice_id = voice_id
            creation.voice_speed = voice_speed
            creation.current_task_id = None
            db.commit()
            return {
                "success": True,
                "task_type": TaskType.BATCH_AUDIO_GENERATION,
                "creation_id": creation_id,
                "voice_id": voice_id,
                "voice_speed": voice_speed,
                "total": 0,
                "success_count": 0,
                "failed_count": 0,
                "audio_url": creation.audio_url,
                "subtitle_url": creation.subtitle_url,
                "message": "音频和字幕已存在，跳过生成",
                "skipped": True,
                "results": []
            }
        
        # 更新创作的 voice_id 和 voice_speed
        creation.voice_id = voice_id
        creation.voice_speed = voice_speed
        db.commit()
        
        # 查询所有场景和分镜
        scenes = (
            db.query(Scene)
            .options(selectinload(Scene.shots))
            .filter(Scene.creation_id == creation_id)
            .order_by(Scene.scene_id)
            .all()
        )
        
        # 收集所有需要生成音频的分镜
        all_shots: List[Dict[str, Any]] = []
        for scene in scenes:
            for shot in sorted(scene.shots, key=lambda s: s.shot_number):
                # 处理所有有旁白的分镜（每次都重新生成音频）
                if shot.narration:
                    all_shots.append({
                        "shot_id": shot.shot_id,
                        "shot_title": shot.title,
                        "shot_number": shot.shot_number,
                        "scene_id": scene.scene_id,
                    })
        
        total_shots = len(all_shots)
        if total_shots == 0:
            logger.info(f"创作 {creation_id} 没有需要生成音频的分镜")
            creation.status = CreationStatus.AUDIO_GENERATED
            creation.current_task_id = None
            db.commit()
            return {
                "success": True,
                "task_type": TaskType.BATCH_AUDIO_GENERATION,
                "creation_id": creation_id,
                "total": 0,
                "message": "没有需要生成音频的分镜",
                "results": []
            }
        
        logger.info(f"开始为创作 {creation_id} 生成 {total_shots} 个分镜的音频")
        
        # 更新任务状态
        self.update_state(
            state="PROGRESS",
            meta={
                "task_type": TaskType.BATCH_AUDIO_GENERATION,
                "creation_id": creation_id,
                "voice_id": voice_id,
                "total": total_shots,
                "completed": 0,
                "success_count": 0,
                "failed_count": 0,
                "status": f"开始生成 {total_shots} 个分镜音频",
                "stage": "generating_audio",
            }
        )
        
        # 使用线程池并发执行（最多 3 个并发）
        results = []
        success_count = 0
        failed_count = 0
        
        max_workers = min(3, total_shots)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_shot = {
                executor.submit(_generate_single_shot_audio, shot["shot_id"], creation_id, voice_id, voice_speed): shot
                for shot in all_shots
            }
            
            for future in as_completed(future_to_shot):
                shot_info = future_to_shot[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result.get("success"):
                        success_count += 1
                    else:
                        failed_count += 1
                    
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "task_type": TaskType.BATCH_AUDIO_GENERATION,
                            "creation_id": creation_id,
                            "total": total_shots,
                            "completed": success_count + failed_count,
                            "success_count": success_count,
                            "failed_count": failed_count,
                            "status": f"音频生成: {success_count + failed_count}/{total_shots}",
                            "stage": "generating_audio",
                        }
                    )
                except Exception as e:
                    failed_count += 1
                    results.append({
                        "shot_id": shot_info["shot_id"],
                        "success": False,
                        "error": str(e)
                    })
        
        # 合并音频
        self.update_state(
            state="PROGRESS",
            meta={
                "task_type": TaskType.BATCH_AUDIO_GENERATION,
                "creation_id": creation_id,
                "total": total_shots,
                "completed": total_shots,
                "success_count": success_count,
                "failed_count": failed_count,
                "status": "正在合并音频...",
                "stage": "merging_audio",
            }
        )
        
        merged_audio_url = _merge_audio_files(results, creation_id)
        
        # 生成字幕
        self.update_state(
            state="PROGRESS",
            meta={
                "task_type": TaskType.BATCH_AUDIO_GENERATION,
                "creation_id": creation_id,
                "total": total_shots,
                "completed": total_shots,
                "success_count": success_count,
                "failed_count": failed_count,
                "status": "正在生成字幕...",
                "stage": "generating_subtitle",
            }
        )
        
        subtitle_url = _generate_and_upload_srt(results, creation_id)
        
        # 更新创作状态
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if creation:
            if merged_audio_url:
                creation.audio_url = merged_audio_url
            if subtitle_url:
                creation.subtitle_url = subtitle_url
            if failed_count == 0:
                creation.status = CreationStatus.AUDIO_GENERATED
            creation.current_task_id = None
            db.commit()
        
        # 清理结果中的 audio_bytes
        for r in results:
            r.pop("audio_bytes", None)
        
        logger.info(
            f"创作 {creation_id} 音频生成完成: "
            f"总数={total_shots}, 成功={success_count}, 失败={failed_count}"
        )
        
        return {
            "success": failed_count == 0,
            "task_type": TaskType.BATCH_AUDIO_GENERATION,
            "creation_id": creation_id,
            "voice_id": voice_id,
            "total": total_shots,
            "success_count": success_count,
            "failed_count": failed_count,
            "audio_url": merged_audio_url,
            "subtitle_url": subtitle_url,
            "results": results
        }
        
    except Exception as e:
        error_msg = f"创作音频生成任务失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        try:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                db.commit()
        except Exception:
            pass
        
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.BATCH_AUDIO_GENERATION,
                "creation_id": creation_id,
                "error": error_msg,
            }
        )
        raise BaseServiceException(message=error_msg)
    finally:
        db.close()
