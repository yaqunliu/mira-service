"""
Agent 专用视频生成 Tasks

独立于现有的 step8_video_gen_task，专门为 Agent 流程设计
支持三种生成模式：first_last_frame / first_frame_only / reference_image
"""

from typing import Dict, Any, Optional, List
from celery import group
from sqlalchemy.orm.attributes import flag_modified

from app.core.celery_app import celery_app
from app.core.logger import logger
from app.db.session import get_sync_session
from app.models import Creation, Scene, Shot, Character
from app.utils.ai_client import AIClient
from app.utils.upload_helper import UploadHelper


# ==================== 辅助函数 ====================

def _get_video_model_config(creation: Creation) -> Dict[str, Any]:
    """
    获取视频生成模型配置
    """
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
    
    # 2. 尝试使用角色图（取第一个有图片的角色）
    if shot.characters:
        for char in shot.characters:
            if char.image_url:
                logger.info(f"[AgentVideoTask] 使用角色图作为参考: character_id={char.character_id}")
                return char.image_url
    
    # 3. 尝试从 Creation 的 characters 中查找
    creation = shot.scene.creation if shot.scene else None
    if creation and creation.characters:
        for char in creation.characters:
            if char.image_url:
                logger.info(f"[AgentVideoTask] 使用创作角色图作为参考: character_id={char.character_id}")
                return char.image_url
    
    return None


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
    """
    根据模式调用对应的视频生成 API
    
    Returns:
        video_url: 生成的视频 URL
    """
    logger.info(f"[AgentVideoTask] 生成视频: mode={mode}, model={model}, duration={duration}s")
    
    # 根据模型选择时长映射
    if "doubao" in model:
        # 火山 Seedance 支持 4-12 秒
        video_duration = min(max(int(duration), 4), 12)
    elif "Wan-AI" in model:
        # Wan-AI 支持 5/10/15秒
        if duration <= 5:
            video_duration = 5
        elif duration <= 10:
            video_duration = 10
        else:
            video_duration = 15
    elif "vidu" in model:
        # Vidu 支持 1-10秒
        video_duration = min(max(int(duration), 1), 10)
    else:
        # 默认 Sora2 支持 4/8/12秒
        if duration <= 4:
            video_duration = 4
        elif duration <= 8:
            video_duration = 8
        else:
            video_duration = 12
    
    # 根据模式选择 API
    if mode == "first_last_frame":
        # 首尾帧模式
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
            # Sora2 不支持首尾帧，降级为首帧模式
            logger.warning(f"[AgentVideoTask] {model} 不支持首尾帧模式，降级为首帧模式")
            video_url = ai_client.generate_video_by_image_sora2(
                image_url=start_image_url,
                prompt=video_prompt,
                duration=video_duration,
            )
    
    elif mode == "first_frame_only":
        # 首帧模式
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
        # 参考图模式
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


# ==================== Celery Tasks ====================

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
    
    Args:
        shot_id: 分镜 ID
        creation_uuid: 创作 UUID
        
    Returns:
        {
            "shot_id": int,
            "success": True/False,
            "video_url": str,
            "duration": float,
            "error": str (仅失败时)
        }
    """
    import time
    import math
    from datetime import datetime
    
    start_time = time.time()
    freeze_record_id = None
    
    try:
        logger.info(f"[AgentVideoTask] 开始生成视频: shot_id={shot_id}")
        
        # 更新任务状态
        self.update_state(state='PROGRESS', meta={
            'progress': 10,
            'status': '准备生成视频...',
            'shot_id': shot_id,
        })
        
        with get_sync_session() as db:
            # 1. 查询 shot 数据
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if not shot:
                raise ValueError(f"分镜不存在: shot_id={shot_id}")
            
            # 获取 creation
            creation = db.query(Creation).filter(
                Creation.uuid == creation_uuid
            ).first()
            if not creation:
                raise ValueError(f"创作不存在: creation_uuid={creation_uuid}")
            
            # 2. 获取视频生成参数
            extra_data = shot.extra_data or {}
            video_prompt = extra_data.get("video_prompt")
            generation_mode = extra_data.get("generation_mode", "first_frame_only")
            
            if not video_prompt:
                raise ValueError(f"分镜 {shot_id} 没有视频提示词")
            
            # 获取图片 URL
            start_image_url = shot.image_url
            end_image_url = extra_data.get("end_frame_image_url")
            reference_image_url = None
            
            # 如果是 reference_image 模式，查找参考图
            if generation_mode == "reference_image":
                reference_image_url = _select_reference_image(shot, db)
                if not reference_image_url:
                    # 降级为 first_frame_only（如果有首帧图）
                    if start_image_url:
                        logger.warning(f"[AgentVideoTask] 找不到参考图，降级为 first_frame_only")
                        generation_mode = "first_frame_only"
                    else:
                        raise ValueError(f"分镜 {shot_id} 没有可用的参考图片")
            
            # 获取模型配置
            model_config = _get_video_model_config(creation)
            model = model_config["model"]
            aspect_ratio = model_config["aspect_ratio"]
            
            # 获取时长
            duration = shot.video_duration or 5
            
            # 3. 冻结积分
            from app.services.points_service import PointsService
            from app.utils.model_prices import ModelPrices
            
            # 计算积分
            cost = ModelPrices.calculate_video_cost(model, duration)
            required_points = int(math.ceil(cost * 100))
            
            try:
                freeze_record = PointsService.freeze_points(
                    db=db,
                    user_id=creation.owner_id,
                    points=required_points,
                    operation_type="generate_video",
                    creation_id=creation.creation_id,
                    novel_id=creation.novel_id,
                    description=f"Agent 生成视频（分镜 {shot.title or shot_id}）",
                    extra_data={
                        "shot_id": shot_id,
                        "video_model": model,
                        "generation_mode": generation_mode,
                    }
                )
                freeze_record_id = freeze_record.record_id
                logger.info(f"[AgentVideoTask] 冻结积分: {required_points} 点")
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
        
        # 4. 生成视频（在 session 外执行，避免长时间占用连接）
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
        
        # 5. 更新数据库
        self.update_state(state='PROGRESS', meta={
            'progress': 90,
            'status': '保存视频结果...',
            'shot_id': shot_id,
        })
        
        with get_sync_session() as db:
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                shot.video_url = video_url
                shot.video_status = "completed"
                
                if not shot.status_detail:
                    shot.status_detail = {}
                shot.status_detail["video_status"] = "completed"
                shot.status_detail["video_completed_at"] = datetime.utcnow().isoformat()
                flag_modified(shot, "status_detail")
                
                db.commit()
            
            # 6. 确认积分
            if freeze_record_id:
                try:
                    PointsService.confirm_frozen_points(db, freeze_record_id)
                    logger.info(f"[AgentVideoTask] 积分确认成功: freeze_record_id={freeze_record_id}")
                except Exception as confirm_err:
                    logger.error(f"[AgentVideoTask] 积分确认失败: {confirm_err}")
        
        total_time = time.time() - start_time
        logger.info(f"[AgentVideoTask] 分镜 {shot_id} 视频生成完成, 耗时 {total_time:.1f}s")
        
        return {
            "shot_id": shot_id,
            "success": True,
            "video_url": video_url,
            "duration": duration,
            "generation_mode": generation_mode,
            "total_time": total_time,
        }
        
    except Exception as e:
        logger.error(f"[AgentVideoTask] 视频生成失败: shot_id={shot_id}, error={e}")
        
        # 释放冻结的积分
        if freeze_record_id:
            try:
                with get_sync_session() as db:
                    from app.services.points_service import PointsService
                    PointsService.release_frozen_points(db, freeze_record_id, reason=str(e))
                    logger.info(f"[AgentVideoTask] 已释放冻结积分: freeze_record_id={freeze_record_id}")
            except Exception as release_err:
                logger.error(f"[AgentVideoTask] 释放积分失败: {release_err}")
        
        # 更新 shot 状态为失败
        try:
            with get_sync_session() as db:
                shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
                if shot:
                    shot.video_status = "failed"
                    if not shot.status_detail:
                        shot.status_detail = {}
                    shot.status_detail["video_status"] = "failed"
                    shot.status_detail["video_error"] = str(e)
                    shot.status_detail["video_failed_at"] = datetime.utcnow().isoformat()
                    flag_modified(shot, "status_detail")
                    db.commit()
        except Exception as update_err:
            logger.error(f"[AgentVideoTask] 更新失败状态失败: {update_err}")
        
        return {
            "shot_id": shot_id,
            "success": False,
            "error": str(e),
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
    
    Args:
        creation_uuid: 创作 UUID
        
    Returns:
        {
            "success": True/False,
            "creation_uuid": str,
            "total": int,
            "group_id": str,
            "shot_task_ids": {shot_id: task_id, ...},
            "message": str,
        }
    """
    try:
        logger.info(f"[AgentVideoTask] 批量派发视频生成任务: creation_uuid={creation_uuid}")
        
        with get_sync_session() as db:
            # 查询创作
            creation = db.query(Creation).filter(
                Creation.uuid == creation_uuid
            ).first()
            
            if not creation:
                return {
                    "success": False,
                    "error": f"创作不存在: {creation_uuid}",
                }
            
            # 查询所有分镜
            shots = db.query(Shot).join(Scene).filter(
                Scene.creation_id == creation.creation_id
            ).order_by(Shot.shot_id).all()
            
            # 筛选需要生成视频的分镜
            # 条件：有 video_prompt 且没有 video_url
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
            
            logger.info(f"[AgentVideoTask] 创作 {creation_uuid} 开始生成 {len(shots_to_generate)} 个分镜视频")
        
        # 为每个分镜创建独立任务
        tasks = group([
            agent_generate_single_shot_video_task.s(
                shot_id=sid,
                creation_uuid=creation_uuid,
            )
            for sid in shots_to_generate
        ])
        
        # 派发任务组
        group_result = tasks.apply_async()
        
        # 保存每个子任务的 ID
        shot_task_ids = {}
        for i, async_result in enumerate(group_result.results):
            shot_task_ids[shots_to_generate[i]] = async_result.id
        
        logger.info(f"[AgentVideoTask] 已派发 {len(shots_to_generate)} 个视频生成任务, group_id={group_result.id}")
        
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
        return {
            "success": False,
            "creation_uuid": creation_uuid,
            "error": str(e),
        }
