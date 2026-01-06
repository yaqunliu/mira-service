"""
完整视频生成任务
将音频生成、字幕生成、视频生成合并到一个任务中
前端只需调用一次，等待最终视频生成完成
"""
import os
import uuid
import random
import tempfile
import subprocess
import httpx
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
from app.utils.font_utils import ensure_font_exists
from app.core.logger import logger
from app.utils.us3 import US3Client
from app.utils.upload_helper import upload_helper
from app.utils.points_deduction import deduct_points_for_video, deduct_points_for_audio
from app.core.config import settings
from app.models.user import User
from datetime import datetime


# ============== 音频相关函数 ==============

def _get_audio_duration_ms(audio_bytes: bytes) -> int:
    """获取音频时长（毫秒）"""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        
        audio = AudioSegment.from_mp3(tmp_path)
        duration_ms = len(audio)
        return duration_ms
    except Exception as e:
        logger.warning(f"获取音频时长失败: {e}")
        return 0
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass


def _format_srt_time(ms: int) -> str:
    """将毫秒转换为 SRT 时间格式"""
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    milliseconds = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _generate_single_shot_audio(shot_id: int, creation_id: int, voice_id: str, voice_speed: float = 1.0) -> dict:
    """生成单个分镜的音频"""
    db: Session = SessionLocal()
    temp_file_path = None
    scene_id = 0
    shot_number = 0
    try:
        shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
        if not shot:
            raise NotFoundError(detail=f"分镜不存在: shot_id={shot_id}")
        
        # 保存 scene_id 和 shot_number 用于错误处理
        scene_id = shot.scene_id
        shot_number = shot.shot_number
        
        if not shot.narration:
            return {
                "shot_id": shot_id,
                "shot_number": shot_number,
                "scene_id": scene_id,
                "success": False,
                "error": "没有旁白文本",
                "skipped": True
            }
        
        fish_client = get_fish_audio_client()
        # 将 voice_speed 转换为 Fish Audio 的 speed 参数
        # Fish Audio 的 speed 范围是 0-2.0，前端传入的 voice_speed 范围也是 0-2
        # 直接使用，但需要确保在有效范围内
        fish_speed = max(0.0, min(2.0, voice_speed))
        audio_bytes = fish_client.text_to_speech_bytes(
            text=shot.narration,
            reference_id=voice_id,
            format="mp3",
            speed=fish_speed
        )
        
        duration_ms = _get_audio_duration_ms(audio_bytes)
        
        temp_fd, temp_file_path = tempfile.mkstemp(suffix=".mp3")
        with os.fdopen(temp_fd, 'wb') as tmp_file:
            tmp_file.write(audio_bytes)
        
        # 获取用户UUID用于构建上传路径
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if not creation:
            raise NotFoundError(detail=f"创作不存在: creation_id={creation_id}")
        
        user = db.query(User).filter(User.user_id == creation.owner_id).first()
        if not user:
            raise ValueError(f"用户不存在: user_id={creation.owner_id}")
        user_uuid = user.uuid
        
        # 获取环境变量和时间戳
        env = getattr(settings, 'ENV', 'dev')
        time_str = datetime.now().strftime('%Y%m%d')
        
        # 使用统一的上传工具上传文件
        audio_uuid = str(uuid.uuid4())
        filename = f"audio/{creation_id}/{shot_id}/audio_{audio_uuid}.mp3"
        
        upload_result = upload_helper.upload_file(
            local_file=temp_file_path,
            user_uuid=user_uuid,
            file_type="audio",  # 文件类型
            filename=filename,
            time_str=time_str
        )
        
        if not upload_result.get('success'):
            raise Exception(f"音频上传失败: {upload_result.get('message')}")
        
        # 使用外网URL保存到数据库
        audio_url = upload_result.get('external_url', upload_result.get('put_key'))
        
        shot.audio_url = audio_url
        shot.audio_duration = duration_ms
        db.commit()
        
        return {
            "shot_id": shot_id,
            "shot_number": shot.shot_number,
            "scene_id": shot.scene_id,
            "success": True,
            "audio_url": audio_url,
            "duration_ms": duration_ms,
            "narration": shot.narration,
            "audio_bytes": audio_bytes
        }
        
    except Exception as e:
        logger.error(f"分镜 {shot_id} 音频生成失败: {e}")
        db.rollback()
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
            except:
                pass
        db.close()


def _merge_audio_files(audio_results: List[Dict], creation_id: int, user_uuid: str, time_str: str) -> Optional[str]:
    """合并多个音频文件"""
    temp_files = []
    merged_path = None
    
    try:
        sorted_results = sorted(
            [r for r in audio_results if r.get("success") and r.get("audio_bytes")],
            key=lambda x: (x.get("scene_id", 0), x.get("shot_number", 0))
        )
        
        if not sorted_results:
            return None
        
        combined = AudioSegment.empty()
        for result in sorted_results:
            audio_bytes = result.get("audio_bytes")
            if audio_bytes:
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp.write(audio_bytes)
                    temp_files.append(tmp.name)
                segment = AudioSegment.from_mp3(temp_files[-1])
                combined += segment
        
        if len(combined) == 0:
            return None
        
        merged_fd, merged_path = tempfile.mkstemp(suffix=".mp3")
        os.close(merged_fd)
        combined.export(merged_path, format="mp3", bitrate="128k")
        
        # 使用统一的上传工具上传文件
        audio_uuid = str(uuid.uuid4())
        filename = f"audio/{creation_id}/merged_audio_{audio_uuid}.mp3"
        
        upload_result = upload_helper.upload_file(
            local_file=merged_path,
            user_uuid=user_uuid,
            file_type="audio",  # 文件类型
            filename=filename,
            time_str=time_str
        )
        
        if not upload_result.get('success'):
            raise Exception(f"合并音频上传失败: {upload_result.get('message')}")
        
        # 返回外网URL
        return upload_result.get('external_url', upload_result.get('put_key'))
        
    except Exception as e:
        logger.error(f"音频合并失败: {e}")
        return None
    finally:
        for tmp_path in temp_files:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except:
                pass
        if merged_path and os.path.exists(merged_path):
            try:
                os.remove(merged_path)
            except:
                pass


def _generate_srt(audio_results: List[Dict], creation_id: int, user_uuid: str, time_str: str) -> Optional[str]:
    """生成 SRT 字幕文件"""
    temp_path = None
    try:
        sorted_results = sorted(
            [r for r in audio_results if r.get("success") and r.get("duration_ms")],
            key=lambda x: (x.get("scene_id", 0), x.get("shot_number", 0))
        )
        
        if not sorted_results:
            return None
        
        srt_lines = []
        current_time = 0
        for idx, result in enumerate(sorted_results, 1):
            duration = result.get("duration_ms", 0)
            text = result.get("narration", "").strip()
            
            if text:
                start_time = _format_srt_time(current_time)
                end_time = _format_srt_time(current_time + duration)
                srt_lines.extend([str(idx), f"{start_time} --> {end_time}", text, ""])
            
            current_time += duration
        
        srt_content = "\n".join(srt_lines)
        if not srt_content.strip():
            return None
        
        temp_fd, temp_path = tempfile.mkstemp(suffix=".srt")
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            f.write(srt_content)
        
        # 使用统一的上传工具上传文件
        srt_uuid = str(uuid.uuid4())
        filename = f"subtitles/{creation_id}/subtitle_{srt_uuid}.srt"
        
        upload_result = upload_helper.upload_file(
            local_file=temp_path,
            user_uuid=user_uuid,
            file_type="subtitles",  # 文件类型
            filename=filename,
            time_str=time_str
        )
        
        if not upload_result.get('success'):
            raise Exception(f"字幕上传失败: {upload_result.get('message')}")
        
        # 返回外网URL
        return upload_result.get('external_url', upload_result.get('put_key'))
        
    except Exception as e:
        logger.error(f"字幕生成失败: {e}")
        return None
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass


# ============== 视频相关函数 ==============

VIDEO_EFFECTS = [
    # 平移特效：使用基于帧数的线性插值，让移动更平滑
    # 从左到右：从0平滑移动到 (iw-iw/zoom)，使用 on/duration 进行线性插值
    {"name": "pan_left_to_right", "filter": "zoompan=z=1.3:d={duration}:x='(iw-iw/zoom)*on/{duration}':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=30"},
    # 从右到左：从 (iw-iw/zoom) 平滑移动到 0
    {"name": "pan_right_to_left", "filter": "zoompan=z=1.3:d={duration}:x='(iw-iw/zoom)*(1-on/{duration})':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=30"},
    # 从上到下：从0平滑移动到 (ih-ih/zoom)
    {"name": "pan_top_to_bottom", "filter": "zoompan=z=1.3:d={duration}:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{duration}':s=1920x1080:fps=30"},
    # 从下到上：从 (ih-ih/zoom) 平滑移动到 0
    {"name": "pan_bottom_to_top", "filter": "zoompan=z=1.3:d={duration}:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*(1-on/{duration})':s=1920x1080:fps=30"},
]


def _download_file(url: str, suffix: str = "") -> str:
    """下载文件到临时路径"""
    with httpx.Client(timeout=60.0) as client:
        response = client.get(url)
        response.raise_for_status()
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, 'wb') as f:
            f.write(response.content)
        return path


def _generate_shot_video(image_path: str, duration_ms: int, output_path: str) -> bool:
    """从图片生成视频片段（带随机特效）"""
    try:
        effect = random.choice(VIDEO_EFFECTS)
        duration_seconds = duration_ms / 1000.0
        # 计算总帧数，确保特效持续整个视频时长
        # fps=30，所以总帧数 = 时长(秒) * 30
        duration_frames = int(round(duration_seconds * 30))
        # 确保至少生成1帧
        if duration_frames < 1:
            duration_frames = 1
        filter_str = effect["filter"].format(duration=duration_frames)
        
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", image_path,
            "-vf", filter_str, "-t", str(duration_seconds),
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"FFmpeg 生成视频失败: {result.stderr}")
            logger.error(f"执行的命令: {' '.join(cmd)}")
        return result.returncode == 0
    except Exception as e:
        logger.error(f"生成视频片段失败: {e}")
        return False


def _generate_single_shot_video(shot_id: int, image_url: str, duration_ms: int, shot_number: int, scene_id: int = 0) -> dict:
    """生成单个分镜的视频片段"""
    image_path = None
    video_path = None
    try:
        # 下载图片
        image_path = _download_file(image_url, suffix=".png")
        
        # 创建临时视频文件
        fd, video_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        
        # 生成视频
        if _generate_shot_video(image_path, duration_ms, video_path):
            return {
                "shot_id": shot_id,
                "shot_number": shot_number,
                "scene_id": scene_id,
                "success": True,
                "video_path": video_path,
            }
        else:
            return {
                "shot_id": shot_id,
                "shot_number": shot_number,
                "scene_id": scene_id,
                "success": False,
                "error": "视频生成失败"
            }
    except Exception as e:
        logger.error(f"分镜 {shot_id} 视频生成失败: {e}")
        return {
            "shot_id": shot_id,
            "shot_number": shot_number,
            "scene_id": scene_id,
            "success": False,
            "error": str(e)
        }
    finally:
        # 清理图片文件（视频文件需要保留用于后续拼接）
        if image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
            except:
                pass


def _concat_videos(video_paths: List[str], output_path: str) -> bool:
    """拼接多个视频"""
    try:
        fd, list_path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, 'w') as f:
            for path in video_paths:
                f.write(f"file '{path.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n")
        
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", output_path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        os.remove(list_path)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"视频拼接失败: {e}")
        return False


def _merge_video_audio_subtitle(video_path: str, audio_path: str, subtitle_path: str, output_path: str) -> bool:
    """合并视频、音频和字幕"""
    try:
        if subtitle_path:
            # 转义字幕路径（只转义单引号，冒号不需要转义）
            subtitle_escaped = subtitle_path.replace("'", "\\'")
            
            # 获取字体文件路径
            font_path = ensure_font_exists()
            if font_path:
                # 获取字体目录和字体名称（不带扩展名）
                font_dir = os.path.dirname(font_path)
                font_name = os.path.splitext(os.path.basename(font_path))[0]
                # 转义路径（只转义单引号）
                font_dir_escaped = font_dir.replace("'", "\\'")
                # 使用 fontsdir 指定字体目录，Fontname 使用字体文件名（不带扩展名）
                # 这是 Linux 上更可靠的方式
                force_style = f"Fontname={font_name},FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2"
                vf_filter = f"subtitles='{subtitle_escaped}':fontsdir='{font_dir_escaped}':force_style='{force_style}'"
                logger.info(f"使用字体: {font_path} (目录: {font_dir}, 名称: {font_name})")
            else:
                logger.warning("字体不存在，使用默认字体")
                vf_filter = f"subtitles='{subtitle_escaped}':force_style='FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2'"
            
            cmd = [
                "ffmpeg", "-y", 
                "-i", video_path, 
                "-i", audio_path,
                "-vf", vf_filter,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-c:a", "aac", "-b:a", "192k", "-shortest",
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y", 
                "-i", video_path, 
                "-i", audio_path,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-preset", "veryfast", "-shortest",
                output_path
            ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error(f"FFmpeg 合并失败: {result.stderr}")
            logger.error(f"执行的命令: {' '.join(cmd)}")
        return result.returncode == 0
    except Exception as e:
        logger.error(f"合并失败: {e}")
        return False


# ============== 主任务 ==============

@celery_app.task(bind=True, name="generate_full_video_task")
def generate_full_video_task(self, creation_id: int, voice_id: str, voice_speed: float = 1.0, force_regenerate: bool = False):
    """
    完整视频生成任务
    
    流程：
    1. 生成所有分镜的音频
    2. 合并音频 + 生成字幕
    3. 为每个分镜图片生成带特效的视频
    4. 拼接视频 + 合并音频字幕
    5. 上传最终视频
    
    Args:
        creation_id: 创作ID
        voice_id: Fish Audio 语音模型ID
        voice_speed: 语速设置，范围 0-10，默认 1.0
        force_regenerate: 是否强制重新生成
    """
    db: Session = SessionLocal()
    temp_files = []
    
    try:
        ##X## Debug 模式下抛出测试异常 - 测试完整视频生成错误
        # if settings.DEBUG:
        #     raise Exception("测试完整视频生成错误")
        
        # 获取创作信息
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if not creation:
            raise NotFoundError(detail=f"创作不存在: creation_id={creation_id}")
        
        # 预先下载字体文件，确保合成视频时字体可用
        font_path = ensure_font_exists()
        if font_path:
            logger.info(f"字体文件准备就绪: {font_path}")
        else:
            logger.warning("字体文件准备失败，将使用默认字体")
        
        creation.voice_id = voice_id
        creation.voice_speed = voice_speed
        
        # 更新步骤状态：处理中
        from app.services.creation_service import CreationService
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="videoGeneration",
            status="processing",
            task_id=self.request.id,
            commit=False
        )
        
        db.commit()
        
        # 检查是否已生成音频和字幕，如果已存在且不强制重新生成，则跳过音频生成阶段
        merged_audio_url = None
        subtitle_url = None
        if not force_regenerate and creation.audio_url and creation.subtitle_url:
            logger.info(f"创作 {creation_id} 音频和字幕已存在，跳过音频生成阶段")
            merged_audio_url = creation.audio_url
            subtitle_url = creation.subtitle_url
            # 更新创作状态
            if merged_audio_url:
                creation.audio_url = merged_audio_url
            if subtitle_url:
                creation.subtitle_url = subtitle_url
            db.commit()
        
        # 获取所有分镜
        scenes = (
            db.query(Scene)
            .options(selectinload(Scene.shots))
            .filter(Scene.creation_id == creation_id)
            .order_by(Scene.scene_id)
            .all()
        )
        
        all_shots = []
        for scene in scenes:
            for shot in sorted(scene.shots, key=lambda s: s.shot_number):
                if shot.narration and shot.image_url:
                    all_shots.append({
                        "shot_id": shot.shot_id,
                        "shot_number": shot.shot_number,
                        "scene_id": shot.scene_id,
                        "image_url": shot.image_url,
                    })
        
        total_shots = len(all_shots)
        if total_shots == 0:
            creation.current_task_id = None
            db.commit()
            return {"success": False, "error": "没有可处理的分镜（需要旁白和图片）"}
        
        # ========== 阶段1: 生成音频（如果已存在则跳过）==========
        if merged_audio_url and subtitle_url:
            logger.info("跳过音频生成，使用已有音频和字幕")
            audio_results = []  # 空结果，直接进入视频生成阶段
        else:
            self.update_state(state="PROGRESS", meta={
                "task_type": TaskType.VIDEO_MERGE,
                "creation_id": creation_id,
                "stage": "generating_audio",
                "stage_name": "生成音频",
                "total_stages": 5,
                "current_stage": 1,
                "total": total_shots,
                "completed": 0,
                "status": f"开始生成 {total_shots} 个分镜音频"
            })
            
            audio_results = []
            success_count = 0
            
            max_workers = min(3, total_shots)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_shot = {
                    executor.submit(_generate_single_shot_audio, shot["shot_id"], creation_id, voice_id, voice_speed): shot
                    for shot in all_shots
                }
                
                for future in as_completed(future_to_shot):
                    result = future.result()
                    audio_results.append(result)
                    if result.get("success"):
                        success_count += 1
                    
                    self.update_state(state="PROGRESS", meta={
                        "task_type": TaskType.VIDEO_MERGE,
                        "creation_id": creation_id,
                        "stage": "generating_audio",
                        "stage_name": "生成音频",
                        "total_stages": 5,
                        "current_stage": 1,
                        "total": total_shots,
                        "completed": len(audio_results),
                        "status": f"音频生成: {len(audio_results)}/{total_shots}"
                    })
        
        # ========== 阶段2: 批量扣除音频生成积分 ==========
        # 统计所有成功生成的音频，一次性扣除积分
        if audio_results:
            successful_audio_results = [r for r in audio_results if r.get("success")]
            if successful_audio_results:
                total_text_bytes = 0
                total_duration_seconds = 0.0
                shot_count = 0
                
                for result in successful_audio_results:
                    narration = result.get("narration", "")
                    if narration:
                        total_text_bytes += len(narration.encode('utf-8'))
                    duration_ms = result.get("duration_ms", 0)
                    if duration_ms:
                        total_duration_seconds += duration_ms / 1000.0
                    shot_count += 1
                
                if total_text_bytes > 0:
                    try:
                        deduct_points_for_audio(
                            db=db,
                            user_id=creation.owner_id,
                            text_bytes=total_text_bytes,
                            audio_duration_seconds=total_duration_seconds,
                            model_name=settings.FISH_AUDIO_DEFAULT_VOICE_ID or "s1",
                            creation_id=creation_id,
                            novel_id=creation.novel_id,
                            description=f"批量生成音频（{shot_count}个分镜，总时长{total_duration_seconds:.1f}秒）",
                            shot_id=None  # 批量操作，不关联单个分镜
                        )
                        logger.info(
                            f"创作 {creation_id} 音频生成积分扣除成功: "
                            f"{shot_count}个分镜, {total_text_bytes}字节, {total_duration_seconds:.1f}秒"
                        )
                    except Exception as e:
                        logger.error(
                            f"创作 {creation_id} 音频生成积分扣除失败: {str(e)} | "
                            f"user_id={creation.owner_id}, text_bytes={total_text_bytes}, "
                            f"audio_duration={total_duration_seconds:.1f}s, shot_count={shot_count}",
                            exc_info=True
                        )
                        # 积分扣除失败不影响音频生成流程，只记录错误
        
        # ========== 阶段3: 合并音频+字幕（如果已存在则跳过）==========
        if not merged_audio_url or not subtitle_url:
            self.update_state(state="PROGRESS", meta={
                "task_type": TaskType.VIDEO_MERGE,
                "creation_id": creation_id,
                "stage": "merging_audio",
                "stage_name": "合并音频和字幕",
                "total_stages": 5,
                "current_stage": 3,
                "status": "正在合并音频..."
            })
            
            # 获取用户UUID和时间戳
            user = db.query(User).filter(User.user_id == creation.owner_id).first()
            if not user:
                raise ValueError(f"用户不存在: user_id={creation.owner_id}")
            user_uuid = user.uuid
            time_str = datetime.now().strftime('%Y%m%d')
            
            merged_audio_url = _merge_audio_files(audio_results, creation_id, user_uuid, time_str)
            subtitle_url = _generate_srt(audio_results, creation_id, user_uuid, time_str)
            
            # 更新创作
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if merged_audio_url:
                creation.audio_url = merged_audio_url
            if subtitle_url:
                creation.subtitle_url = subtitle_url
            db.commit()
        else:
            logger.info("跳过音频合并和字幕生成，使用已有文件")
        
        # ========== 阶段4: 生成视频片段 ==========
        self.update_state(state="PROGRESS", meta={
            "task_type": TaskType.VIDEO_MERGE,
            "creation_id": creation_id,
            "stage": "generating_video",
            "stage_name": "生成视频片段",
            "total_stages": 5,
            "current_stage": 4,
            "total": total_shots,
            "completed": 0,
            "status": f"开始生成 {total_shots} 个视频片段"
        })
        
        # 按 (scene_id, shot_number) 排序音频结果
        # 如果跳过了音频生成，从数据库查询分镜的音频时长
        if not audio_results:
            sorted_audio = []
            for shot_info in all_shots:
                shot = db.query(Shot).filter(Shot.shot_id == shot_info["shot_id"]).first()
                if shot and shot.audio_duration:
                    sorted_audio.append({
                        "shot_id": shot.shot_id,
                        "shot_number": shot.shot_number,
                        "scene_id": shot.scene_id,
                        "duration_ms": shot.audio_duration,
                    })
            sorted_audio.sort(key=lambda x: (x.get("scene_id", 0), x.get("shot_number", 0)))
        else:
            sorted_audio = sorted(
                [r for r in audio_results if r.get("success") and r.get("duration_ms")],
                key=lambda x: (x.get("scene_id", 0), x.get("shot_number", 0))
            )
        
        # 准备视频生成任务数据
        video_tasks = []
        for audio_result in sorted_audio:
            shot_id = audio_result["shot_id"]
            duration_ms = audio_result["duration_ms"]
            shot_number = audio_result["shot_number"]
            
            # 找到对应的图片URL
            shot_info = next((s for s in all_shots if s["shot_id"] == shot_id), None)
            if not shot_info:
                continue
            
            video_tasks.append({
                "shot_id": shot_id,
                "image_url": shot_info["image_url"],
                "duration_ms": duration_ms,
                "shot_number": shot_number,
                "scene_id": audio_result.get("scene_id") or shot_info.get("scene_id"),
            })
        
        if not video_tasks:
            raise Exception("没有可生成视频的分镜")
        
        # 并发生成视频片段
        video_results = []
        max_workers = min(3, len(video_tasks))  # 限制并发数，避免过多FFmpeg进程
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_task = {
                executor.submit(
                    _generate_single_shot_video,
                    task["shot_id"],
                    task["image_url"],
                    task["duration_ms"],
                    task["shot_number"],
                    task["scene_id"]
                ): task
                for task in video_tasks
            }
            
            for future in as_completed(future_to_task):
                result = future.result()
                video_results.append(result)
                
                # 将成功的视频路径添加到临时文件列表，以便后续清理
                if result.get("success") and result.get("video_path"):
                    temp_files.append(result["video_path"])
                
                self.update_state(state="PROGRESS", meta={
                    "task_type": TaskType.VIDEO_MERGE,
                    "creation_id": creation_id,
                    "stage": "generating_video",
                    "stage_name": "生成视频片段",
                    "total_stages": 5,
                    "current_stage": 4,
                    "total": len(video_tasks),
                    "completed": len(video_results),
                    "status": f"视频片段: {len(video_results)}/{len(video_tasks)}"
                })
        
        # 收集成功的视频片段
        video_clips = [
            {
                "path": r["video_path"],
                "shot_number": r["shot_number"],
                "scene_id": r.get("scene_id", 0)
            }
            for r in video_results
            if r.get("success") and r.get("video_path")
        ]
        
        if not video_clips:
            raise Exception("没有成功生成的视频片段")
        
        # 按 (scene_id, shot_number) 顺序排序
        video_clips.sort(key=lambda x: (x.get("scene_id", 0), x.get("shot_number", 0)))
        
        # 扣除视频生成积分（按片段数，每个片段1积分）
        shot_count = len(video_clips)
        try:
            deduct_points_for_video(
                db=db,
                user_id=creation.owner_id,
                shot_count=shot_count,
                creation_id=creation_id,
                novel_id=creation.novel_id,
                description=f"生成视频（{shot_count}个片段）"
            )
        except Exception as e:
            logger.opt(exception=True).error("视频生成积分扣除失败: {}", str(e))
            # 积分扣除失败不影响视频生成流程，只记录错误
        
        # ========== 阶段5: 合并最终视频 ==========
        self.update_state(state="PROGRESS", meta={
            "task_type": TaskType.VIDEO_MERGE,
            "creation_id": creation_id,
            "stage": "merging_video",
            "stage_name": "合并最终视频",
            "total_stages": 5,
            "current_stage": 5,
            "status": "正在拼接视频..."
        })
        
        # 拼接视频
        fd, concat_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        temp_files.append(concat_path)
        
        if not _concat_videos([c["path"] for c in video_clips], concat_path):
            raise Exception("视频拼接失败")
        
        # 下载音频和字幕
        audio_path = None
        srt_path = None
        
        if merged_audio_url:
            audio_path = _download_file(merged_audio_url, suffix=".mp3")
            temp_files.append(audio_path)
        
        if subtitle_url:
            srt_path = _download_file(subtitle_url, suffix=".srt")
            temp_files.append(srt_path)
        
        # 合并
        fd, final_path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        temp_files.append(final_path)
        
        self.update_state(state="PROGRESS", meta={
            "task_type": TaskType.VIDEO_MERGE,
            "creation_id": creation_id,
            "stage": "merging_video",
            "stage_name": "合并最终视频",
            "total_stages": 5,
            "current_stage": 5,
            "status": "正在合并音频和字幕..."
        })
        
        if audio_path:
            if not _merge_video_audio_subtitle(concat_path, audio_path, srt_path, final_path):
                logger.warning("合并音频字幕失败，使用纯视频")
                final_path = concat_path
        else:
            final_path = concat_path
        
        # 上传最终视频
        self.update_state(state="PROGRESS", meta={
            "task_type": TaskType.VIDEO_MERGE,
            "creation_id": creation_id,
            "stage": "uploading",
            "stage_name": "上传视频",
            "total_stages": 5,
            "current_stage": 5,
            "status": "正在上传最终视频..."
        })
        
        # 获取用户UUID和时间戳
        user = db.query(User).filter(User.user_id == creation.owner_id).first()
        if not user:
            raise ValueError(f"用户不存在: user_id={creation.owner_id}")
        user_uuid = user.uuid
        time_str = datetime.now().strftime('%Y%m%d')
        
        # 使用统一的上传工具上传文件
        video_uuid = str(uuid.uuid4())
        filename = f"videos/{creation_id}/final_video_{video_uuid}.mp4"
        
        upload_result = upload_helper.upload_file(
            local_file=final_path,
            user_uuid=user_uuid,
            file_type="videos",  # 文件类型
            filename=filename,
            time_str=time_str
        )
        
        if not upload_result.get('success'):
            raise Exception(f"视频上传失败: {upload_result.get('message')}")
        
        # 使用外网URL保存到数据库
        video_url = upload_result.get('external_url', upload_result.get('put_key'))
        
        # 更新创作状态
        creation.video_url = video_url
        creation.status = CreationStatus.COMPLETED
        creation.current_task_id = None
        
        # 更新步骤状态：成功
        from app.services.creation_service import CreationService
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="videoGeneration",
            status="success",
            commit=False
        )
        
        db.commit()
        
        logger.info(f"创作 {creation_id} 视频生成完成: {video_url}")
        
        return {
            "success": True,
            "task_type": TaskType.VIDEO_MERGE,
            "creation_id": creation_id,
            "video_url": video_url,
            "audio_url": merged_audio_url,
            "subtitle_url": subtitle_url,
        }
        
    except BaseServiceException as e:
        # BaseServiceException 直接重新抛出，不进行包装
        try:
            # 重新查询 creation，确保能够设置 current_task_id
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                
                # 更新步骤状态：失败
                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation_id,
                    step_name="videoGeneration",
                    status="failed",
                    error=str(e),
                    commit=False
                )
                
                db.commit()
        except Exception as cleanup_error:
            logger.opt(exception=True).error("清理 current_task_id 失败: {}", str(cleanup_error))
            db.rollback()
        
        error_msg = str(e)
        exc_type = type(e).__name__
        exc_module = type(e).__module__
        self.update_state(state="FAILURE", meta={
            "task_type": TaskType.VIDEO_MERGE,
            "creation_id": creation_id,
            "error": error_msg,
            "exc_type": f"{exc_module}.{exc_type}",
            "exc_message": error_msg,
        })
        raise
    except Exception as e:
        error_msg = str(e)
        # 测试异常直接抛出，不进行包装
        is_test_exception = "测试错误" in error_msg
        
        if not is_test_exception:
            error_msg = f"视频生成任务失败: {error_msg}"
            logger.opt(exception=True).error("{}", error_msg)
        
        try:
            # 重新查询 creation，确保能够设置 current_task_id
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                
                # 更新步骤状态：失败
                from app.services.creation_service import CreationService
                CreationService.update_creation_step_status(
                    db=db,
                    creation_id=creation_id,
                    step_name="videoGeneration",
                    status="failed",
                    error=error_msg,
                    commit=False
                )
                
                db.commit()
        except Exception as cleanup_error:
            logger.opt(exception=True).error("清理 current_task_id 失败: {}", str(cleanup_error))
            db.rollback()
        
        exc_type = type(e).__name__
        exc_module = type(e).__module__
        self.update_state(state="FAILURE", meta={
            "task_type": TaskType.VIDEO_MERGE,
            "creation_id": creation_id,
            "error": error_msg,
            "exc_type": f"{exc_module}.{exc_type}",
            "exc_message": error_msg,
        })
        
        # 测试异常直接抛出，其他异常包装成 BaseServiceException
        if is_test_exception:
            raise
        else:
            raise BaseServiceException(message=error_msg)
        
    finally:
        for path in temp_files:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except:
                pass
        db.close()

