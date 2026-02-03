"""
视频提示词生成任务 - 步骤 7
"""
from sqlalchemy.orm import Session
from app.core.celery_app import celery_app
from app.core.logger import logger
from app.db.base import _get_sync_session_factory
from app.models.creation import Creation
from app.models.shot import Shot
from app.services.points_service import PointsService
from app.utils.video_prompt_generator import (
    generate_video_prompt as generate_video_prompt_util,
    generate_video_only_prompt as generate_video_only_prompt_util
)
import traceback


@celery_app.task(
    bind=True, 
    name="generate_video_prompt_task",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def generate_video_prompt_task(
    self,
    shot_id: int,
    creation_id: int,
    freeze_record_id: int = None
):
    """
    为单个分镜生成视频提示词
    Args:
        shot_id: 分镜ID
        creation_id: 作品ID
        freeze_record_id: 积分冻结记录ID（用于后续扣除）
    """
    db: Session = _get_sync_session_factory()()
    try:
        shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
        if not shot:
            raise ValueError(f"Shot {shot_id} not found")

        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()

        # 准备输入数据
        image_prompt = shot.image_prompt or ""
        script = shot.description or ""
        dialogues = []
        
        # V5：获取首尾帧提示词
        extra_data = shot.extra_data or {}
        start_frame_prompt = image_prompt  # 首帧提示词（兼容旧版，使用 image_prompt）
        end_frame_prompt = extra_data.get("end_frame_image_prompt")  # 尾帧提示词
        
        logger.info(f"Shot {shot_id} 首尾帧提示词: start_frame={len(start_frame_prompt) if start_frame_prompt else 0}字, end_frame={len(end_frame_prompt) if end_frame_prompt else 0}字")

        # 解析 narration 字段 (可能是JSON字符串或已经是list)
        narration_list = []
        if shot.narration:
            if isinstance(shot.narration, str):
                # 如果是字符串，尝试解析为JSON
                try:
                    import json
                    narration_list = json.loads(shot.narration)
                    logger.info(f"Shot {shot_id} narration 从JSON字符串解析成功")
                except json.JSONDecodeError as e:
                    logger.error(f"Shot {shot_id} narration JSON解析失败: {e}, 原始值: {shot.narration}")
                    narration_list = []
            elif isinstance(shot.narration, list):
                narration_list = shot.narration
                logger.info(f"Shot {shot_id} narration 已经是list类型")
            else:
                logger.warning(f"Shot {shot_id} narration 类型未知: {type(shot.narration)}")

        # 调试：打印narration的解析结果
        logger.info(f"=" * 80)
        logger.info(f"Shot {shot_id} narration 解析结果")
        logger.info(f"类型: {type(narration_list)}")
        logger.info(f"长度: {len(narration_list) if isinstance(narration_list, list) else 'N/A'}")
        logger.info(f"内容: {narration_list}")
        logger.info(f"=" * 80)

        # 从narration_list解析台词（兼容多种格式）
        # 重要：所有narration（包括旁白和对话）都要提取出来
        if narration_list and isinstance(narration_list, list):
            for narr in narration_list:
                if isinstance(narr, dict):
                    speaker = None
                    content = None

                    # 格式1: {"type": "dialogue", "character": "张三", "text": "..."}
                    if narr.get('type') == 'dialogue':
                        speaker = narr.get('character', '未知')
                        content = narr.get('text', '')
                    # 格式2: {"type": "narration", "text": "..."}（旁白）
                    elif narr.get('type') == 'narration':
                        speaker = '旁白'
                        content = narr.get('text', '')
                    # 格式3: {"角色": "张三", "内容": "..."}
                    elif '角色' in narr and '内容' in narr:
                        speaker = narr.get('角色', '旁白')
                        content = narr.get('内容', '')
                    # 格式4: 只有内容，默认为旁白
                    elif '内容' in narr:
                        speaker = '旁白'
                        content = narr.get('内容', '')
                    # 格式5: 直接有text字段，默认为旁白
                    elif 'text' in narr:
                        speaker = '旁白'
                        content = narr.get('text', '')

                    # 添加到dialogues列表（不管是对话还是旁白都要添加）
                    if content and content.strip():
                        dialogues.append({speaker: content})

        logger.info(f"Shot {shot_id} 解析到 {len(dialogues)} 条台词/旁白: {dialogues}")

        # 获取关联的角色信息（使用智能状态识别）
        from app.utils.character_state_identifier import generate_character_identity

        characters = []
        if hasattr(shot, 'characters') and shot.characters:
            for char in shot.characters:
                # 从角色的basic_info解析年龄段
                basic_info = char.basic_info if isinstance(char.basic_info, dict) else {}
                age_group = basic_info.get('age_group', '未知') if basic_info else '未知'

                # 组合外观描述
                appearance_parts = []
                if char.appearance:
                    appearance_parts.append(char.appearance)
                if char.clothing:
                    appearance_parts.append(f"穿着{char.clothing}")
                if char.hair:
                    appearance_parts.append(f"发型：{char.hair}")

                appearance_full = '，'.join(appearance_parts) if appearance_parts else ''

                # 生成智能角色标识（考虑状态：湿透、受伤、变身等）
                character_identity = generate_character_identity(
                    name=char.name,
                    age_group=age_group,
                    appearance=char.appearance or '',
                    clothing=char.clothing or '',
                    shot_description=script  # 使用分镜剧本作为上下文
                )

                characters.append({
                    'name': char.name,
                    'age_group': age_group,
                    'appearance': appearance_full,
                    'identity': character_identity  # 添加角色标识
                })

                logger.info(f"角色识别: {char.name} -> {character_identity}")

        # 从creation获取模型配置
        extra_data = creation.extra_data or {} if creation else {}
        llm_model = extra_data.get('llm_model', 'gpt-4')
        video_model = extra_data.get('video_model', 'sora2')
        
        # 判断是否使用“纯视频”提示词范式
        # 1. 明确指定了 video_only 为 True
        # 2. 或者使用的视频模型是纯视频模型（Wan-AI, Vidu）
        video_only = extra_data.get('video_only', False)
        if not video_only and video_model in ["Wan-AI/Wan2.6-I2V", "viduq2-pro", "viduq2-turbo"]:
            video_only = True
            logger.info(f"由于视频模型为 {video_model}，自动切换至纯视频提示词范式")

        # 生成视频提示词 - 使用独立的工具函数（V6版本返回字典，三维度格式：画面+背景音+台词）
        if video_only:
            logger.info(f"使用【纯视频】提示词范式生成提示词 (V6)")
            prompt_result = generate_video_only_prompt_util(
                llm_model=llm_model,
                shot=shot,
                script=script,
                characters=characters,
                start_frame_prompt=start_frame_prompt,
                end_frame_prompt=end_frame_prompt
            )
        else:
            logger.info(f"使用【标准】提示词范式生成提示词 (V6)")
            prompt_result = generate_video_prompt_util(
                llm_model=llm_model,
                shot=shot,
                script=script,
                dialogues=dialogues,
                characters=characters,
                start_frame_prompt=start_frame_prompt,
                end_frame_prompt=end_frame_prompt
            )

        # V5：从返回的字典中提取数据
        video_prompt = prompt_result.get("video_prompt", "")
        cut_method = prompt_result.get("cut_method", "smooth_transition")
        cut_reason = prompt_result.get("cut_reason", "")

        # 存储到shot.extra_data
        if not shot.extra_data:
            shot.extra_data = {}
        shot.extra_data['video_prompt'] = video_prompt
        shot.extra_data['cut_method'] = cut_method
        shot.extra_data['cut_reason'] = cut_reason
        db.commit()

        logger.info(f"Generated video prompt for shot {shot_id}: {video_prompt[:100]}...")
        logger.info(f"Cut method: {cut_method}, reason: {cut_reason}")

        # 扣除冻结的积分（如果有冻结记录）
        if freeze_record_id:
            PointsService.unfreeze_and_deduct(db, freeze_record_id, success=True)

        return {
            "status": "success",
            "shot_id": shot_id,
            "video_prompt": video_prompt,
            "cut_method": cut_method,
            "cut_reason": cut_reason
        }

    except Exception as e:
        logger.error(f"Error generating video prompt for shot {shot_id}: {str(e)}")
        logger.error(traceback.format_exc())

        # 解冻积分（失败）
        if freeze_record_id:
            try:
                PointsService.unfreeze_and_deduct(db, freeze_record_id, success=False)
            except:
                pass

        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_all_video_prompts_task")
def generate_all_video_prompts_task(self, creation_id: int):
    """
    为作品中所有分镜批量生成视频提示词
    """
    db: Session = _get_sync_session_factory()()
    try:
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if not creation:
            raise ValueError(f"Creation {creation_id} not found")

        # 获取所有shots
        shots = []
        for scene in creation.scenes:
            shots.extend(scene.shots)

        success_count = 0
        failed_count = 0

        for shot in shots:
            try:
                # 检查是否已有video_prompt
                existing_prompt = (shot.extra_data or {}).get('video_prompt')
                if existing_prompt:
                    logger.info(f"Shot {shot.shot_id} already has video_prompt, skipping")
                    success_count += 1
                    continue

                # 同步生成（因为是在Celery任务中）
                generate_video_prompt_task(
                    shot_id=shot.shot_id,
                    creation_id=creation_id,
                    freeze_record_id=None  # 批量生成不预冻结积分，后扣
                )
                success_count += 1

            except Exception as e:
                logger.error(f"Failed to generate prompt for shot {shot.shot_id}: {str(e)}")
                failed_count += 1

        logger.info(f"Batch video prompt generation completed: {success_count} success, {failed_count} failed")

        return {
            "status": "completed",
            "success_count": success_count,
            "failed_count": failed_count,
            "total": len(shots)
        }

    except Exception as e:
        logger.error(f"Error in batch video prompt generation: {str(e)}")
        raise
    finally:
        db.close()
