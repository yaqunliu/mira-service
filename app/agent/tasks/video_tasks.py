"""
Agent 专用视频生成 Tasks

⚠️ 核心原则：这些 Tasks 独立于现有的 step8_video_gen_task 等任务
"""

import os
import tempfile
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from app.core.celery_app import celery_app
from app.core.logger import logger


@celery_app.task(bind=True, name="agent.generate_video")
def agent_generate_video_task(
    self,
    creation_uuid: str,
    shot_id: int,
    start_image_url: str,
    end_image_url: Optional[str] = None,
    prompt: Optional[str] = None,
    duration: float = 5.0,
    model: str = "kling",
) -> Dict[str, Any]:
    """
    Agent 专用视频生成任务
    
    Args:
        creation_uuid: 创作项目 UUID
        shot_id: 分镜 ID
        start_image_url: 首帧图片 URL
        end_image_url: 尾帧图片 URL（可选，用于首尾帧模式）
        prompt: 视频运动提示词（可选）
        duration: 视频时长（秒）
        model: 生成模型（默认 kling）
        
    Returns:
        {
            "status": "success" | "failed",
            "shot_id": int,
            "video_url": str,
            "duration": float,
            "error": str  # 仅失败时
        }
    """
    try:
        logger.info(f"[Agent Task] 开始生成视频: shot_id={shot_id}")
        
        self.update_state(state='PROGRESS', meta={
            'progress': 10,
            'status': '开始生成视频...',
            'shot_id': shot_id,
        })
        
        from app.services.video_generation import VideoGenerationService
        
        video_service = VideoGenerationService()
        
        self.update_state(state='PROGRESS', meta={
            'progress': 20,
            'status': '提交视频生成请求...',
            'shot_id': shot_id,
        })
        
        # 根据是否有尾帧选择生成模式
        if end_image_url:
            # 首尾帧模式
            result = video_service.generate_with_frames(
                start_image_url=start_image_url,
                end_image_url=end_image_url,
                prompt=prompt,
                duration=duration,
                model=model,
            )
        else:
            # 单图模式
            result = video_service.generate(
                image_url=start_image_url,
                prompt=prompt,
                duration=duration,
                model=model,
            )
        
        self.update_state(state='PROGRESS', meta={
            'progress': 90,
            'status': '保存结果到数据库...',
            'shot_id': shot_id,
        })
        
        # 更新数据库
        from app.db.session import get_sync_session
        from app.models.shot import Shot
        
        with get_sync_session() as db:
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                shot.video_url = result["url"]
                db.commit()
        
        logger.info(f"[Agent Task] 视频生成成功: shot_id={shot_id}")
        
        return {
            "status": "success",
            "shot_id": shot_id,
            "video_url": result["url"],
            "duration": duration,
            "generation_time": result.get("time", 0),
        }
        
    except Exception as e:
        error_message = str(e)
        logger.error(f"[Agent Task] 视频生成失败: shot_id={shot_id}, error={error_message}")
        
        # AI 分析错误原因
        error_analysis = _analyze_video_error(error_message)
        
        # 更新数据库记录错误
        try:
            from app.db.session import get_sync_session
            from app.models.shot import Shot
            from sqlalchemy.orm.attributes import flag_modified
            from datetime import datetime
            
            with get_sync_session() as db:
                shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
                if shot:
                    shot.video_status = "failed"
                    if not shot.status_detail:
                        shot.status_detail = {}
                    shot.status_detail["video_status"] = "failed"
                    shot.status_detail["video_error"] = error_message
                    shot.status_detail["video_error_analysis"] = error_analysis
                    shot.status_detail["video_failed_at"] = datetime.utcnow().isoformat()
                    flag_modified(shot, "status_detail")
                    db.commit()
                    logger.info(f"[Agent Task] 已记录错误到数据库: shot_id={shot_id}")
        except Exception as db_err:
            logger.error(f"[Agent Task] 记录错误到数据库失败: {db_err}")
        
        return {
            "status": "failed",
            "shot_id": shot_id,
            "error": error_message,
            "error_analysis": error_analysis,
            "recoverable": error_analysis.get("is_retryable", True),
        }


# ==================== Batch Video Generation ====================
# 以下代码从 app/tasks/agent_video_task.py 迁移过来

import time
import math
from datetime import datetime
from typing import List
from celery import group
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import get_sync_session
from app.models import Creation, Scene, Shot, Character
from app.utils.ai_client import AIClient
from app.utils.upload_helper import UploadHelper


def _get_video_model_config(creation: Creation) -> Dict[str, Any]:
    """获取视频生成模型配置"""
    extra_data = creation.extra_data or {}
    video_model = extra_data.get("video_model", "doubao-seedance-1-5-pro-251215")
    aspect_ratio = extra_data.get("aspect_ratio", "16:9")
    
    return {
        "model": video_model,
        "aspect_ratio": aspect_ratio,
    }


def _select_reference_image(shot: Shot, db) -> Optional[str]:
    """
    为 reference_image 模式选择参考图
    优先级：场景图 > 角色图
    """
    # 1. 尝试使用场景图
    if shot.scene and shot.scene.image_url:
        logger.info(f"[AgentVideoTask] 使用场景图作为参考: scene_id={shot.scene.scene_id}")
        return shot.scene.image_url
    
    # 2. 尝试使用角色图
    if shot.characters:
        for char in shot.characters:
            if char.image_url:
                logger.info(f"[AgentVideoTask] 使用角色图作为参考: character_id={char.character_id}")
                return char.image_url
    
    # 3. 从 Creation 查找
    creation = shot.scene.creation if shot.scene else None
    if creation and creation.characters:
        for char in creation.characters:
            if char.image_url:
                logger.info(f"[AgentVideoTask] 使用创作角色图作为参考: character_id={char.character_id}")
                return char.image_url
    
    return None


def _analyze_video_error(error_message: str) -> Dict[str, Any]:
    """
    AI 分析视频生成错误原因
    
    Args:
        error_message: 原始错误信息
        
    Returns:
        错误分析结果，包含类型、原因和建议
    """
    try:
        # 常见错误模式匹配
        error_lower = error_message.lower()
        
        # 敏感内容检测
        if "sensitive" in error_lower or "sensitivecontent" in error_lower:
            return {
                "error_type": "sensitive_content",
                "error_category": "内容审核",
                "reason": "生成的视频内容可能包含敏感信息（如暴力、血腥、色情等），被 AI 模型拒绝生成",
                "suggestion": "建议修改分镜描述，避免敏感内容描述，或使用更委婉的表达方式",
                "is_retryable": False,
                "raw_error": error_message,
            }
        
        # 图片质量问题
        if "image" in error_lower and ("quality" in error_lower or "blur" in error_lower or "unclear" in error_lower):
            return {
                "error_type": "image_quality",
                "error_category": "图片质量",
                "reason": "输入的图片质量不佳（模糊、不清晰或内容不完整）",
                "suggestion": "建议重新生成分镜图片，确保图片清晰、内容完整后再生成视频",
                "is_retryable": True,
                "raw_error": error_message,
            }
        
        # 图片内容问题
        if "image" in error_lower and ("content" in error_lower or "invalid" in error_lower):
            return {
                "error_type": "image_content",
                "error_category": "图片内容",
                "reason": "输入的图片内容不符合要求（可能包含多个人物、文字或水印）",
                "suggestion": "建议重新生成分镜图片，确保画面简洁、主体明确、无文字水印",
                "is_retryable": True,
                "raw_error": error_message,
            }
        
        # 超时错误
        if "timeout" in error_lower or "time out" in error_lower:
            return {
                "error_type": "timeout",
                "error_category": "服务超时",
                "reason": "视频生成服务响应超时",
                "suggestion": "可以稍后重试，或检查网络连接状态",
                "is_retryable": True,
                "raw_error": error_message,
            }
        
        # 服务不可用
        if "unavailable" in error_lower or "service" in error_lower or "503" in error_lower:
            return {
                "error_type": "service_unavailable",
                "error_category": "服务不可用",
                "reason": "视频生成服务暂时不可用",
                "suggestion": "可以稍后重试，或联系技术支持",
                "is_retryable": True,
                "raw_error": error_message,
            }
        
        # 配额/额度不足
        if "quota" in error_lower or "limit" in error_lower or "insufficient" in error_lower:
            return {
                "error_type": "quota_exceeded",
                "error_category": "额度不足",
                "reason": "API 调用额度已用完或超出限制",
                "suggestion": "请联系管理员增加额度，或等待额度重置",
                "is_retryable": False,
                "raw_error": error_message,
            }
        
        # 默认未知错误
        return {
            "error_type": "unknown",
            "error_category": "未知错误",
            "reason": f"视频生成过程中出现未知错误: {error_message[:100]}",
            "suggestion": "建议稍后重试，如果问题持续存在请联系技术支持",
            "is_retryable": True,
            "raw_error": error_message,
        }
        
    except Exception as e:
        logger.error(f"[AgentVideoTask] 错误分析失败: {e}")
        return {
            "error_type": "analysis_failed",
            "error_category": "分析失败",
            "reason": f"无法分析错误原因，原始错误: {error_message[:100]}",
            "suggestion": "建议稍后重试",
            "is_retryable": True,
            "raw_error": error_message,
        }


def _generate_video_by_mode(
    ai_client: AIClient,
    mode: str,
    start_image_url: Optional[str],
    end_image_url: Optional[str],
    reference_image_url: Optional[str],
    video_prompt: str,
    duration: int,
    model: str,
    aspect_ratio: str = "16:9",
) -> str:
    """根据模式调用对应的视频生成 API"""
    logger.info(f"[AgentVideoTask] 生成视频: mode={mode}, model={model}, duration={duration}s")
    
    # 根据模型选择时长映射
    if "doubao" in model:
        video_duration = min(max(int(duration), 4), 12)
    elif "Wan-AI" in model:
        video_duration = 5 if duration <= 5 else (10 if duration <= 10 else 15)
    elif "vidu" in model:
        video_duration = min(max(int(duration), 1), 10)
    else:
        video_duration = 4 if duration <= 4 else (8 if duration <= 8 else 12)
    
    # 根据模式选择 API
    if mode == "first_last_frame":
        if not start_image_url or not end_image_url:
            raise ValueError("first_last_frame 模式需要首帧和尾帧图片")
        
        if "doubao" in model:
            video_url = ai_client.generate_video_by_image_doubao_modelverse(
                image_url=start_image_url,
                prompt=video_prompt,
                duration=video_duration,
                aspect_ratio=aspect_ratio,
                last_frame_image_url=end_image_url,
            )
        elif "Wan-AI" in model:
            video_url = ai_client.generate_video_by_image_wan_ai(
                image_url=start_image_url,
                prompt=video_prompt,
                duration=video_duration,
                last_frame_image_url=end_image_url,
            )
        elif "vidu" in model:
            video_url = ai_client.generate_video_by_image_vidu(
                image_url=start_image_url,
                prompt=video_prompt,
                duration=video_duration,
                model=model,
                last_frame_image_url=end_image_url,
            )
        else:
            logger.warning(f"[AgentVideoTask] {model} 不支持首尾帧模式，降级为首帧模式")
            video_url = ai_client.generate_video_by_image_sora2(
                image_url=start_image_url,
                prompt=video_prompt,
                duration=video_duration,
            )
    
    elif mode == "first_frame_only":
        if not start_image_url:
            raise ValueError("first_frame_only 模式需要首帧图片")
        
        if "doubao" in model:
            video_url = ai_client.generate_video_by_image_doubao_modelverse(
                image_url=start_image_url,
                prompt=video_prompt,
                duration=video_duration,
                aspect_ratio=aspect_ratio,
            )
        elif "Wan-AI" in model:
            video_url = ai_client.generate_video_by_image_wan_ai(
                image_url=start_image_url,
                prompt=video_prompt,
                duration=video_duration,
            )
        elif "vidu" in model:
            video_url = ai_client.generate_video_by_image_vidu(
                image_url=start_image_url,
                prompt=video_prompt,
                duration=video_duration,
                model=model,
            )
        else:
            video_url = ai_client.generate_video_by_image_sora2(
                image_url=start_image_url,
                prompt=video_prompt,
                duration=video_duration,
            )
    
    elif mode == "reference_image":
        if not reference_image_url:
            raise ValueError("reference_image 模式需要参考图片")
        
        if "doubao" in model:
            video_url = ai_client.generate_video_by_image_doubao_modelverse(
                image_url=reference_image_url,
                prompt=video_prompt,
                duration=video_duration,
                aspect_ratio=aspect_ratio,
            )
        elif "Wan-AI" in model:
            video_url = ai_client.generate_video_by_image_wan_ai(
                image_url=reference_image_url,
                prompt=video_prompt,
                duration=video_duration,
            )
        elif "vidu" in model:
            video_url = ai_client.generate_video_by_image_vidu(
                image_url=reference_image_url,
                prompt=video_prompt,
                duration=video_duration,
                model=model,
            )
        else:
            video_url = ai_client.generate_video_by_image_sora2(
                image_url=reference_image_url,
                prompt=video_prompt,
                duration=video_duration,
            )
    else:
        raise ValueError(f"不支持的生成模式: {mode}")
    
    return video_url


@celery_app.task(bind=True, name="agent_generate_single_shot_video", soft_time_limit=1800, time_limit=1900)
def agent_generate_single_shot_video_task(
    self,
    shot_id: int,
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    单个分镜视频生成任务
    
    从数据库读取 shot 的 video_prompt 和 generation_mode，
    根据 mode 选择对应的 API 生成视频。
    """
    freeze_record_id = None
    start_time = time.time()
    
    try:
        logger.info(f"[AgentVideoTask] 开始生成视频: shot_id={shot_id}")
        
        self.update_state(state='PROGRESS', meta={
            'progress': 10,
            'status': '准备生成视频...',
            'shot_id': shot_id,
        })
        
        with get_sync_session() as db:
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if not shot:
                raise ValueError(f"分镜不存在: shot_id={shot_id}")
            
            creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
            if not creation:
                raise ValueError(f"创作不存在: creation_uuid={creation_uuid}")
            
            # 获取视频生成参数
            extra_data = shot.extra_data or {}
            video_prompt = extra_data.get("video_prompt")
            generation_mode = extra_data.get("generation_mode", "first_frame_only")
            logger.info(f"[AgentVideoTask] 分镜 {shot_id} 生成参数: {extra_data}")
            
            if not video_prompt:
                raise ValueError(f"分镜 {shot_id} 没有视频提示词")
            
            # 获取图片 URL
            start_image_url = shot.image_url
            end_image_url = extra_data.get("end_frame_image_url")
            reference_image_url = None
            
            if generation_mode == "reference_image":
                reference_image_url = _select_reference_image(shot, db)
                if not reference_image_url and start_image_url:
                    logger.warning(f"[AgentVideoTask] 找不到参考图，降级为 first_frame_only")
                    generation_mode = "first_frame_only"
            
            # 获取模型配置
            model_config = _get_video_model_config(creation)
            model = model_config["model"]
            aspect_ratio = model_config["aspect_ratio"]
            duration = shot.video_duration or 5
            
            # 冻结积分
            from app.services.points_service import PointsService
            from app.utils.model_prices import ModelPrices
            
            cost = ModelPrices.calculate_video_cost(model, duration)
            required_points = int(math.ceil(cost * 100))
            
            try:
                freeze_record = PointsService.freeze_points(
                    db=db,
                    user_id=creation.owner_id,
                    points=required_points,
                    operation_type="generate_video",
                    creation_id=creation.creation_id,
                    description=f"Agent 生成视频（分镜 {shot.title or shot_id}）",
                )
                freeze_record_id = freeze_record.record_id
            except Exception as points_err:
                logger.error(f"[AgentVideoTask] 积分冻结失败: {points_err}")
                raise
            
            # 更新 shot 状态
            shot.video_status = "generating"
            if not shot.status_detail:
                shot.status_detail = {}
            shot.status_detail["video_status"] = "generating"
            shot.status_detail["video_started_at"] = datetime.utcnow().isoformat()
            flag_modified(shot, "status_detail")
            db.commit()
        
        # 生成视频
        self.update_state(state='PROGRESS', meta={
            'progress': 30,
            'status': '调用 AI 生成视频...',
            'shot_id': shot_id,
        })
        
        ai_client = AIClient()
        video_url = _generate_video_by_mode(
            ai_client=ai_client,
            mode=generation_mode,
            start_image_url=start_image_url,
            end_image_url=end_image_url,
            reference_image_url=reference_image_url,
            video_prompt=video_prompt,
            duration=duration,
            model=model,
            aspect_ratio=aspect_ratio,
        )
        
        logger.info(f"[AgentVideoTask] 视频生成成功: {video_url[:80]}...")

        # 分离音频视频并上传到 US3
        self.update_state(state='PROGRESS', meta={
            'progress': 80,
            'status': '分离音视频并上传...',
            'shot_id': shot_id,
        })

        try:
            # 下载视频到临时文件
            import requests
            from app.utils.ffmpeg_utils import FFmpegUtils
            from app.utils.upload_helper import upload_helper

            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_video_file:
                temp_video_path = temp_video_file.name

            # 下载视频
            response = requests.get(video_url, timeout=300)
            response.raise_for_status()
            with open(temp_video_path, 'wb') as f:
                f.write(response.content)

            logger.info(f"[AgentVideoTask] 视频下载成功: {temp_video_path}")

            # 分离音频和视频
            video_silent_path = temp_video_path.replace('.mp4', '_silent.mp4')
            audio_path = temp_video_path.replace('.mp4', '.mp3')

            FFmpegUtils.separate_audio_video(
                input_video_path=temp_video_path,
                output_video_path=video_silent_path,
                output_audio_path=audio_path
            )

            logger.info(f"[AgentVideoTask] 音视频分离成功: 视频={video_silent_path}, 音频={audio_path}")

            # 获取 creation 和 user 信息用于上传
            with get_sync_session() as db:
                creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
                if not creation:
                    raise ValueError(f"创作不存在: {creation_uuid}")

                user_uuid = str(creation.owner_id)
                shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
                if not shot:
                    raise ValueError(f"分镜不存在: {shot_id}")

                # 上传静音视频到 US3
                video_filename = f"{shot_id}_{uuid.uuid4().hex[:8]}_silent.mp4"
                video_upload_result = upload_helper.upload_file(
                    local_file=video_silent_path,
                    user_uuid=user_uuid,
                    file_type="videos",
                    filename=video_filename
                )

                if not video_upload_result.get("success"):
                    raise Exception(f"视频上传失败: {video_upload_result.get('message')}")

                video_us3_url = video_upload_result["external_url"]
                logger.info(f"[AgentVideoTask] 视频上传成功: {video_us3_url}")

                # 上传音频到 US3（如果音频存在）
                audio_us3_url = None
                if os.path.exists(audio_path) and os.path.getsize(audio_path) > 0:
                    audio_filename = f"{shot_id}_{uuid.uuid4().hex[:8]}.mp3"
                    audio_upload_result = upload_helper.upload_file(
                        local_file=audio_path,
                        user_uuid=user_uuid,
                        file_type="audio",
                        filename=audio_filename
                    )

                    if audio_upload_result.get("success"):
                        audio_us3_url = audio_upload_result["external_url"]
                        logger.info(f"[AgentVideoTask] 音频上传成功: {audio_us3_url}")

                # 生成版本历史记录
                version_id = str(uuid.uuid4())
                version_record = {
                    "version_id": version_id,
                    "video_url": video_us3_url,
                    "audio_url": audio_us3_url,
                    "video_model": model,
                    "video_duration": duration,
                    "created_at": datetime.utcnow().isoformat(),
                }

                # 更新数据库
                if not shot.extra_data:
                    shot.extra_data = {}

                # 添加版本历史
                if "version_history" not in shot.extra_data:
                    shot.extra_data["version_history"] = []
                shot.extra_data["version_history"].append(version_record)

                # 添加生成记录
                if "generation_records" not in shot.extra_data:
                    shot.extra_data["generation_records"] = []

                generation_record = {
                    "record_id": str(uuid.uuid4()),
                    "type": "video",
                    "model": model,
                    "duration": duration,
                    "generation_mode": generation_mode,
                    "original_url": video_url,
                    "video_url": video_us3_url,
                    "audio_url": audio_us3_url,
                    "created_at": datetime.utcnow().isoformat(),
                    "version_id": version_id,
                }
                shot.extra_data["generation_records"].append(generation_record)

                # 更新 shot 主字段
                shot.video_url = video_us3_url
                shot.audio_url = audio_us3_url
                shot.video_status = "completed"

                if not shot.status_detail:
                    shot.status_detail = {}
                shot.status_detail["video_status"] = "completed"
                shot.status_detail["video_completed_at"] = datetime.utcnow().isoformat()
                shot.status_detail["video_us3_url"] = video_us3_url
                shot.status_detail["audio_us3_url"] = audio_us3_url

                flag_modified(shot, "extra_data")
                flag_modified(shot, "status_detail")
                db.commit()

                logger.info(f"[AgentVideoTask] 数据库更新成功: shot_id={shot_id}, video_url={video_us3_url}, audio_url={audio_us3_url}")

                # 确认积分
                if freeze_record_id:
                    try:
                        PointsService.confirm_frozen_points(db, freeze_record_id)
                    except Exception as confirm_err:
                        logger.error(f"[AgentVideoTask] 积分确认失败: {confirm_err}")

            # 清理临时文件
            try:
                for temp_file in [temp_video_path, video_silent_path, audio_path]:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        logger.debug(f"[AgentVideoTask] 清理临时文件: {temp_file}")
            except Exception as cleanup_err:
                logger.warning(f"[AgentVideoTask] 清理临时文件失败: {cleanup_err}")

            total_time = time.time() - start_time
            return {
                "shot_id": shot_id,
                "success": True,
                "video_url": video_us3_url,
                "audio_url": audio_us3_url,
                "duration": duration,
                "generation_mode": generation_mode,
                "version_id": version_id,
                "total_time": total_time,
            }

        except Exception as process_err:
            logger.error(f"[AgentVideoTask] 音视频处理失败: {process_err}")
            # 如果处理失败，仍然保存原始视频 URL
            with get_sync_session() as db:
                shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
                if shot:
                    shot.video_url = video_url
                    shot.video_status = "completed"
                    if not shot.status_detail:
                        shot.status_detail = {}
                    shot.status_detail["video_status"] = "completed"
                    shot.status_detail["video_completed_at"] = datetime.utcnow().isoformat()
                    shot.status_detail["video_processing_error"] = str(process_err)
                    flag_modified(shot, "status_detail")
                    db.commit()

                if freeze_record_id:
                    try:
                        PointsService.confirm_frozen_points(db, freeze_record_id)
                    except Exception as confirm_err:
                        logger.error(f"[AgentVideoTask] 积分确认失败: {confirm_err}")

            total_time = time.time() - start_time
            return {
                "shot_id": shot_id,
                "success": True,
                "video_url": video_url,
                "duration": duration,
                "generation_mode": generation_mode,
                "processing_error": str(process_err),
                "total_time": total_time,
            }
        
    except Exception as e:
        error_message = str(e)
        logger.error(f"[AgentVideoTask] 视频生成失败: shot_id={shot_id}, error={error_message}")
        
        # AI 分析错误原因
        error_analysis = _analyze_video_error(error_message)
        
        if freeze_record_id:
            try:
                with get_sync_session() as db:
                    from app.services.points_service import PointsService
                    PointsService.release_frozen_points(db, freeze_record_id, reason=error_message)
            except Exception:
                pass
        
        try:
            with get_sync_session() as db:
                shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
                if shot:
                    shot.video_status = "failed"
                    if not shot.status_detail:
                        shot.status_detail = {}
                    shot.status_detail["video_status"] = "failed"
                    shot.status_detail["video_error"] = error_message
                    shot.status_detail["video_error_analysis"] = error_analysis
                    shot.status_detail["video_failed_at"] = datetime.utcnow().isoformat()
                    flag_modified(shot, "status_detail")
                    db.commit()
        except Exception:
            pass
        
        return {
            "shot_id": shot_id,
            "success": False,
            "error": error_message,
            "error_analysis": error_analysis,
            "recoverable": True,
        }


@celery_app.task(bind=True, name="agent_generate_shot_videos")
def agent_generate_shot_videos_task(
    self,
    creation_uuid: str,
) -> Dict[str, Any]:
    """
    批量派发视频生成任务（使用 Celery group）
    
    查询所有需要生成视频的分镜，为每个分镜创建独立任务。
    返回 group_id 和 shot_task_ids 供轮询。
    """
    try:
        logger.info(f"[AgentVideoTask] 批量派发视频生成任务: creation_uuid={creation_uuid}")
        
        with get_sync_session() as db:
            creation = db.query(Creation).filter(Creation.uuid == creation_uuid).first()
            if not creation:
                return {"success": False, "error": f"创作不存在: {creation_uuid}"}
            
            shots = db.query(Shot).join(Scene).filter(
                Scene.creation_id == creation.creation_id
            ).order_by(Shot.shot_id).all()
            
            shots_to_generate = []
            for shot in shots:
                extra_data = shot.extra_data or {}
                video_prompt = extra_data.get("video_prompt")
                if video_prompt and not shot.video_url:
                    shots_to_generate.append(shot.shot_id)
            
            if not shots_to_generate:
                return {
                    "success": True,
                    "creation_uuid": creation_uuid,
                    "total": 0,
                    "shot_task_ids": {},
                    "message": "没有需要生成视频的分镜",
                }
        
        # 派发任务组
        tasks = group([
            agent_generate_single_shot_video_task.s(
                shot_id=sid,
                creation_uuid=creation_uuid,
            )
            for sid in shots_to_generate
        ])
        
        group_result = tasks.apply_async()
        
        shot_task_ids = {}
        for i, async_result in enumerate(group_result.results):
            shot_task_ids[shots_to_generate[i]] = async_result.id
        
        logger.info(f"[AgentVideoTask] 已派发 {len(shots_to_generate)} 个视频任务, group_id={group_result.id}")
        
        return {
            "success": True,
            "creation_uuid": creation_uuid,
            "total": len(shots_to_generate),
            "group_id": group_result.id,
            "shot_task_ids": shot_task_ids,
            "message": f"已启动 {len(shots_to_generate)} 个分镜视频生成任务",
        }
        
    except Exception as e:
        logger.error(f"[AgentVideoTask] 批量派发失败: {e}")
        return {"success": False, "creation_uuid": creation_uuid, "error": str(e)}

