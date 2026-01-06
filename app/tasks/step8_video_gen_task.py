"""
V2 视频生成流程 - 步骤 8: AI 视频生成
"""
import os
import json
from typing import Dict, Any, List

from app.core.celery_app import celery_app
from app.core.logger import logger
from app.db.session import SessionLocal
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.models.creation import Creation
from app.models.shot import Shot
from app.models.scene import Scene
from app.utils.task_types import TaskType
from app.utils.ai_client import AIClient
from app.utils.us3 import US3Client
from app.utils.points_deduction import deduct_points_for_video
from app.utils.ffmpeg_utils import FFmpegUtils
from app.models.user import User
import tempfile
import requests

@celery_app.task(bind=True, name="generate_scene_videos_task")
def generate_scene_videos_task(self, scene_id: int, creation_id: int):
    """
    场景视频生成任务（生成场景下所有分镜的视频）
    """
    db: Session = SessionLocal()
    try:
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.AI_VIDEO_GENERATION,
                'scene_id': scene_id,
                'creation_id': creation_id,
                'status': '正在生成场景视频...'
            }
        )

        scene = db.query(Scene).filter(Scene.scene_id == scene_id).first()
        if not scene:
            raise Exception(f"Scene not found: {scene_id}")

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

        shots = db.query(Shot).filter(Shot.scene_id == scene_id).all()
        if not shots:
            return {"status": "success", "message": "No shots found in scene"}

        ai_client = AIClient()
        us3_client = US3Client()
        
        generated_count = 0
        import uuid
        
        for shot in shots:
            try:
                # 初始化 status_detail
                from datetime import datetime
                if not shot.status_detail:
                    shot.status_detail = {}

                # 更新视频生成状态：开始
                shot.status_detail['video_status'] = 'generating'
                shot.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
                shot.video_status = 'generating'
                db.flush()

                # 即使已有视频也重新生成（因为是强制重新生成场景视频）
                video_prompt = (shot.extra_data or {}).get("video_prompt")
                if not video_prompt:
                    logger.warning(f"No video prompt for shot {shot.shot_id}, using image prompt")
                    video_prompt = shot.image_prompt

                logger.info(f"Regenerating video for shot {shot.shot_id} in scene {scene_id}")

                # 根据 shot 的实际时长选择 Sora2 支持的时长（4/8/12秒）
                shot_duration = shot.video_duration if shot.video_duration else 5  # 默认5秒
                if shot_duration <= 4:
                    video_duration = 4
                elif shot_duration <= 8:
                    video_duration = 8
                else:
                    video_duration = 12

                logger.info(f"Shot时长: {shot_duration}秒，选择Sora2时长: {video_duration}秒")

                # 调用 Sora2 图生视频 API（size参数留空使用API默认值）
                video_url = ai_client.generate_video_by_image_sora2(
                    image_url=shot.image_url,
                    prompt=video_prompt,
                    duration=video_duration
                )

                # 下载视频到临时文件
                temp_video_fd, temp_video_path = tempfile.mkstemp(suffix='.mp4')
                os.close(temp_video_fd)

                try:
                    logger.info(f"下载视频: {video_url}")
                    response = requests.get(video_url, timeout=300)
                    response.raise_for_status()
                    with open(temp_video_path, 'wb') as f:
                        f.write(response.content)

                    # 分离音视频
                    logger.info(f"分离音视频: shot_id={shot.shot_id}")
                    silent_video_path, audio_path = FFmpegUtils.separate_audio_video(temp_video_path)

                    # 上传静音视频到US3
                    video_filename = f"videos/{creation_id}/{shot.shot_id}_{uuid.uuid4().hex[:8]}_silent.mp4"
                    silent_video_url = us3_client.upload_file(silent_video_path, video_filename)
                    logger.info(f"静音视频上传成功: {silent_video_url}")

                    # 上传音频到US3（如果有音频）
                    audio_url = None
                    if audio_path and os.path.exists(audio_path):
                        audio_filename = f"audio/{creation_id}/{shot.shot_id}_{uuid.uuid4().hex[:8]}.mp3"
                        audio_url = us3_client.upload_file(audio_path, audio_filename)
                        logger.info(f"音频上传成功: {audio_url}")
                        # 清理临时音频文件
                        try:
                            os.remove(audio_path)
                        except:
                            pass

                    # 清理临时视频文件
                    try:
                        os.remove(silent_video_path)
                        os.remove(temp_video_path)
                    except:
                        pass

                    shot.video_url = silent_video_url
                    shot.audio_url = audio_url
                    shot.video_duration = float(video_duration)
                    shot.video_status = "completed"

                    # 更新 status_detail：视频生成成功
                    from datetime import datetime
                    if not shot.status_detail:
                        shot.status_detail = {}
                    shot.status_detail['video_status'] = 'completed'
                    shot.status_detail['video_updated_at'] = datetime.utcnow().isoformat()

                    db.flush()

                except Exception as video_error:
                    # 清理临时文件
                    try:
                        os.remove(temp_video_path)
                    except:
                        pass
                    raise video_error

                # 扣除积分（视频生成成功后）
                from app.utils.points_deduction import deduct_points_for_video
                try:
                    deduct_points_for_video(
                        db=db,
                        user_id=creation.owner_id,
                        model_name=ai_client.sora2_model,
                        duration_seconds=video_duration,
                        resolution="720p",  # 720x1280 对应 720p
                        creation_id=creation_id,
                        novel_id=scene.novel_id,
                        shot_id=shot.shot_id
                    )
                    logger.info(f"视频生成积分扣除成功: shot_id={shot.shot_id}")
                except Exception as points_error:
                    logger.error(f"视频生成积分扣除失败: {str(points_error)}")
                    # 积分扣除失败不影响视频生成，记录错误后继续
                db.flush()
                generated_count += 1
                
                # 更新任务进度
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'task_type': TaskType.AI_VIDEO_GENERATION,
                        'scene_id': scene_id,
                        'creation_id': creation_id,
                        'progress': int((generated_count / len(shots)) * 100),
                        'status': f'已生成 {generated_count}/{len(shots)} 个分镜视频'
                    }
                )
                
            except Exception as e:
                logger.error(f"Failed to generate video for shot {shot.shot_id}: {e}")
                shot.video_status = "failed"

                # 更新 status_detail：视频生成失败
                from datetime import datetime
                if not shot.status_detail:
                    shot.status_detail = {}
                shot.status_detail['video_status'] = 'failed'
                shot.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
                shot.status_detail['video_error'] = str(e)

                # 继续处理下一个分镜

        # 更新状态
        scene.status = "completed"
        
        # 清除 creation 的 current_task_id
        creation = db.query(Creation).filter(Creation.creation_id == scene.creation_id).first()
        if creation:
            creation.current_task_id = None
            
            # 更新步骤状态：成功
            from app.services.creation_service import CreationService
            CreationService.update_creation_step_status(
                db=db,
                creation_id=scene.creation_id,
                step_name="videoGeneration",
                status="success",
                commit=False
            )
        
        db.commit()

        return {
            "status": "success",
            "scene_id": scene_id,
            "generated_count": generated_count,
            "total_shots": len(shots)
        }

    except Exception as e:
        logger.error(f"Scene Video Generation Failed: {str(e)}")
        db.rollback()
        raise e
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_single_shot_video_task", soft_time_limit=1800, time_limit=1900)
def generate_single_shot_video_task(self, shot_id: int, creation_id: int, freeze_record_id: int = None):
    """
    单个分镜视频生成任务

    时间限制：
    - soft_time_limit: 1800秒 (30分钟) - 超时后抛出SoftTimeLimitExceeded异常
    - time_limit: 1900秒 (约32分钟) - 硬性终止任务

    Args:
        shot_id: 分镜ID
        creation_id: 作品ID
        freeze_record_id: 积分冻结记录ID（用于后续扣除）
    """
    db: Session = SessionLocal()
    try:
        # 只在Celery上下文中更新状态（检查self.request是否存在）
        if self and hasattr(self, 'request') and self.request.id:
            self.update_state(
                state='PROGRESS',
                meta={
                    'task_type': TaskType.AI_VIDEO_GENERATION,
                    'shot_id': shot_id,
                    'creation_id': creation_id,
                    'status': '正在生成分镜视频...'
                }
            )

        shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
        if not shot:
            raise Exception(f"Shot not found: {shot_id}")

        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()

        # 初始化 status_detail
        from datetime import datetime
        if not shot.status_detail:
            shot.status_detail = {}

        # 更新视频生成状态：开始
        shot.status_detail['video_status'] = 'generating'
        shot.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
        shot.video_status = 'generating'
        flag_modified(shot, 'status_detail')
        db.commit()

        ai_client = AIClient()
        us3_client = US3Client()

        # 检查是否有 video_prompt，如果没有或太简单（降级提示词）则重新生成
        video_prompt = (shot.extra_data or {}).get("video_prompt")
        is_fallback_prompt = video_prompt and video_prompt.startswith("平稳移动，")

        if not video_prompt or is_fallback_prompt:
            logger.info(f"No video_prompt found for shot {shot.shot_id}, generating now...")

            # 更新extra_data状态：生成提示词中
            if not shot.extra_data:
                shot.extra_data = {}
            shot.extra_data['video_prompt_status'] = 'generating'
            flag_modified(shot, 'extra_data')
            db.commit()

            # 准备输入数据
            image_prompt = shot.image_prompt or ""
            script = shot.description or ""
            dialogues = []

            # 解析 narration 字段 (可能是JSON字符串或已经是list)
            narration_list = []
            if shot.narration:
                if isinstance(shot.narration, str):
                    # 如果是字符串，尝试解析为JSON
                    try:
                        import json
                        narration_list = json.loads(shot.narration)
                        logger.info(f"Shot {shot_id} (step8) narration 从JSON字符串解析成功")
                    except json.JSONDecodeError as e:
                        logger.error(f"Shot {shot_id} (step8) narration JSON解析失败: {e}, 原始值: {shot.narration}")
                        narration_list = []
                elif isinstance(shot.narration, list):
                    narration_list = shot.narration
                    logger.info(f"Shot {shot_id} (step8) narration 已经是list类型")
                else:
                    logger.warning(f"Shot {shot_id} (step8) narration 类型未知: {type(shot.narration)}")

            # 调试：打印narration的解析结果
            logger.info(f"=" * 80)
            logger.info(f"Shot {shot_id} (step8) narration 解析结果")
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
            llm_model = extra_data.get('llm_model')
            text_to_image_model = extra_data.get('text_to_image_model')
            image_to_image_model = extra_data.get('image_to_image_model')

            # 生成video_prompt - 使用独立的提示词生成函数
            from app.utils.video_prompt_generator import generate_video_prompt
            video_prompt = generate_video_prompt(
                llm_model=llm_model,
                shot=shot,
                script=script,
                dialogues=dialogues,
                characters=characters
            )

            # 存储到shot.extra_data
            shot.extra_data['video_prompt'] = video_prompt
            shot.extra_data['video_prompt_status'] = 'completed'
            flag_modified(shot, 'extra_data')
            db.commit()
            logger.info(f"Generated video prompt for shot {shot.shot_id}: {video_prompt[:100]}...")

        logger.info(f"Generating video for shot {shot.shot_id}")

        # 根据 shot 的实际时长选择 Sora2 支持的时长（4/8/12秒）
        shot_duration = shot.video_duration if shot.video_duration else 5  # 默认5秒
        if shot_duration <= 4:
            video_duration = 4
        elif shot_duration <= 8:
            video_duration = 8
        else:
            video_duration = 12

        logger.info(f"Shot时长: {shot_duration}秒，选择Sora2时长: {video_duration}秒")

        # 调用 Sora2 图生视频 API（size参数留空使用API默认值）
        video_url = ai_client.generate_video_by_image_sora2(
            image_url=shot.image_url,
            prompt=video_prompt,
            duration=video_duration
        )

        # 下载视频到临时文件
        import uuid
        temp_video_fd, temp_video_path = tempfile.mkstemp(suffix='.mp4')
        os.close(temp_video_fd)

        try:
            logger.info(f"下载视频: {video_url}")
            response = requests.get(video_url, timeout=300)
            response.raise_for_status()
            with open(temp_video_path, 'wb') as f:
                f.write(response.content)

            # 分离音视频
            logger.info(f"分离音视频: shot_id={shot.shot_id}")
            silent_video_path, audio_path = FFmpegUtils.separate_audio_video(temp_video_path)

            # 上传静音视频到US3
            video_put_key = f"videos/{creation_id}/{shot.shot_id}_{uuid.uuid4().hex[:8]}_silent.mp4"
            video_upload_result = us3_client.upload_file(silent_video_path, put_key=video_put_key)

            if not video_upload_result.get('success'):
                raise Exception(f"视频上传失败: {video_upload_result.get('message')}")

            # 生成视频URL
            silent_video_url = us3_client.get_file_url(video_upload_result['key'])
            logger.info(f"静音视频上传成功: {silent_video_url}")

            # 上传音频到US3（如果有音频）
            audio_url = None
            if audio_path and os.path.exists(audio_path):
                audio_put_key = f"audio/{creation_id}/{shot.shot_id}_{uuid.uuid4().hex[:8]}.mp3"
                audio_upload_result = us3_client.upload_file(audio_path, put_key=audio_put_key)

                if audio_upload_result.get('success'):
                    # 生成音频URL
                    audio_url = us3_client.get_file_url(audio_upload_result['key'])
                    logger.info(f"音频上传成功: {audio_url}")
                else:
                    logger.warning(f"音频上传失败: {audio_upload_result.get('message')}")

                # 清理临时音频文件
                try:
                    os.remove(audio_path)
                except:
                    pass

            # 清理临时视频文件
            try:
                os.remove(silent_video_path)
                os.remove(temp_video_path)
            except:
                pass

            shot.video_url = silent_video_url
            shot.audio_url = audio_url
            shot.video_duration = float(video_duration)
            shot.video_status = "completed"

            # 更新 status_detail：视频生成成功
            shot.status_detail['video_status'] = 'completed'
            shot.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
            flag_modified(shot, 'status_detail')

            # 更新extra_data状态：视频生成成功
            if not shot.extra_data:
                shot.extra_data = {}
            shot.extra_data['video_generation_status'] = 'completed'
            flag_modified(shot, 'extra_data')

        except Exception as e:
            # 清理临时文件
            try:
                os.remove(temp_video_path)
            except:
                pass
            raise e

        # 确认冻结的积分（视频生成成功后）
        if freeze_record_id:
            try:
                from app.services.points_service import PointsService
                PointsService.confirm_frozen_points(db, freeze_record_id)
                logger.info(f"视频生成积分扣除成功: shot_id={shot.shot_id}, freeze_record_id={freeze_record_id}")
            except Exception as points_error:
                logger.error(f"视频生成积分扣除失败: {str(points_error)}")
                # 积分扣除失败不影响视频生成，记录错误后继续
        
        # 清除 creation 的 current_task_id
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if creation:
            creation.current_task_id = None
            
        db.commit()

        return {
            "status": "success",
            "shot_id": shot_id,
            "video_url": silent_video_url,
            "duration": float(video_duration)
        }

    except Exception as e:
        logger.error(f"Single Shot Video Generation Failed: {str(e)}")

        # 释放冻结的积分（失败）
        if freeze_record_id:
            try:
                from app.services.points_service import PointsService
                PointsService.release_frozen_points(db, freeze_record_id, reason=str(e))
                logger.info(f"已释放冻结积分: freeze_record_id={freeze_record_id}")
            except:
                pass

        # 更新状态为失败
        try:
            shot = db.query(Shot).filter(Shot.shot_id == shot_id).first()
            if shot:
                shot.video_status = "failed"

                # 更新 status_detail：视频生成失败
                if not shot.status_detail:
                    shot.status_detail = {}
                shot.status_detail['video_status'] = 'failed'
                shot.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
                shot.status_detail['video_error'] = str(e)
                flag_modified(shot, 'status_detail')

                # 更新extra_data状态
                if not shot.extra_data:
                    shot.extra_data = {}
                shot.extra_data['video_generation_status'] = 'failed'
                flag_modified(shot, 'extra_data')

                db.commit()
                logger.info(f"Shot {shot_id} video_status 和 status_detail 已更新为 failed")
        except Exception as update_error:
            logger.error(f"Failed to update shot status to failed: {str(update_error)}")
        raise e
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_all_videos_task", soft_time_limit=7200, time_limit=7300)
def generate_all_videos_task(self, creation_id: int, user_id: int):
    """
    为作品中所有分镜批量生成视频

    时间限制：
    - soft_time_limit: 7200秒 (2小时) - 超时后抛出SoftTimeLimitExceeded异常
    - time_limit: 7300秒 (约2小时) - 硬性终止任务

    流程：
    1. 检查每个shot是否有video_prompt，没有则先生成
    2. 逐个生成视频
    """
    db: Session = SessionLocal()
    try:
        import math
        import traceback
        from datetime import datetime
        from billiard.exceptions import SoftTimeLimitExceeded
        from app.services.points_service import PointsService
        from app.core.exceptions import InsufficientPointsError
        from app.utils.model_prices import ModelPrices

        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if not creation:
            raise ValueError(f"Creation {creation_id} not found")

        # 初始化 creation.extra_data.steps.videoGeneration
        if not creation.extra_data:
            creation.extra_data = {}
        if 'steps' not in creation.extra_data:
            creation.extra_data['steps'] = {}

        # 收集所有shots
        all_shots = []
        for scene in creation.scenes:
            all_shots.extend(scene.shots)

        # 统计需要生成的shots
        shots_to_generate = [s for s in all_shots if s.image_url and not s.video_url]
        total_to_generate = len(shots_to_generate)

        # 设置 videoGeneration step 为 processing
        creation.extra_data['steps']['videoGeneration'] = {
            'status': 'processing',
            'triggered': True,
            'taskId': self.request.id,
            'updatedAt': int(datetime.utcnow().timestamp()),
            'progress': {
                'total': total_to_generate,
                'completed': 0,
                'success': 0,
                'failed': 0,
                'current_shot_id': None
            }
        }
        flag_modified(creation, 'extra_data')
        db.commit()

        logger.info(f"Starting batch video generation for {total_to_generate} shots in creation {creation_id}")

        # 逐个处理每个shot：先生成提示词，再生成视频
        success_count = 0
        failed_count = 0
        skipped_count = 0

        for shot in all_shots:
            if not shot.image_url:
                skipped_count += 1
                continue

            # 检查是否已有视频
            if shot.video_url:
                logger.info(f"Shot {shot.shot_id} already has video, skipping")
                success_count += 1

                # 更新进度（跳过的也算完成）
                creation_refresh = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                if creation_refresh and creation_refresh.extra_data and 'steps' in creation_refresh.extra_data:
                    if 'videoGeneration' in creation_refresh.extra_data['steps']:
                        creation_refresh.extra_data['steps']['videoGeneration']['progress']['completed'] += 1
                        creation_refresh.extra_data['steps']['videoGeneration']['progress']['success'] += 1
                        flag_modified(creation_refresh, 'extra_data')
                        db.commit()

                continue

            # 第一步：确保该shot有video_prompt（如果没有则生成）
            video_prompt = (shot.extra_data or {}).get('video_prompt') if shot.extra_data else None
            if not video_prompt:
                logger.info(f"Generating video_prompt for shot {shot.shot_id}")
                try:
                    # 调用提示词生成任务
                    from app.tasks.step7_video_prompt_gen_task import generate_video_prompt_task
                    # 直接调用函数而不是delay，因为我们已经在Celery任务中
                    result = generate_video_prompt_task(
                        shot_id=shot.shot_id,
                        creation_id=creation_id,
                        freeze_record_id=None
                    )
                    db.refresh(shot)
                    logger.info(f"Generated video_prompt for shot {shot.shot_id}")
                except Exception as e:
                    logger.error(f"Failed to generate prompt for shot {shot.shot_id}: {str(e)}")
                    # 提示词生成失败，跳过该shot的视频生成
                    failed_count += 1

                    # 更新shot状态为失败
                    try:
                        shot_obj = db.query(Shot).filter(Shot.shot_id == shot.shot_id).first()
                        if shot_obj:
                            shot_obj.video_status = "failed"
                            if not shot_obj.status_detail:
                                shot_obj.status_detail = {}
                            shot_obj.status_detail['video_status'] = 'failed'
                            shot_obj.status_detail['video_error'] = f"提示词生成失败: {str(e)}"
                            shot_obj.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
                            flag_modified(shot_obj, 'status_detail')
                            db.commit()
                    except Exception as update_error:
                        logger.error(f"Failed to update shot status: {str(update_error)}")

                    # 更新videoGeneration进度
                    try:
                        creation_refresh = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                        if creation_refresh and creation_refresh.extra_data and 'steps' in creation_refresh.extra_data:
                            if 'videoGeneration' in creation_refresh.extra_data['steps']:
                                creation_refresh.extra_data['steps']['videoGeneration']['progress']['completed'] += 1
                                creation_refresh.extra_data['steps']['videoGeneration']['progress']['failed'] += 1
                                flag_modified(creation_refresh, 'extra_data')
                                db.commit()
                    except Exception as progress_error:
                        logger.error(f"Failed to update videoGeneration progress: {str(progress_error)}")

                    continue  # 跳过该shot，继续处理下一个

            # 第二步：更新videoGeneration进度：当前正在处理的shot_id
            try:
                creation_refresh = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                if creation_refresh and creation_refresh.extra_data and 'steps' in creation_refresh.extra_data:
                    if 'videoGeneration' in creation_refresh.extra_data['steps']:
                        creation_refresh.extra_data['steps']['videoGeneration']['progress']['current_shot_id'] = shot.shot_id
                        creation_refresh.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                        flag_modified(creation_refresh, 'extra_data')
                        db.commit()
            except Exception as progress_error:
                logger.error(f"Failed to update videoGeneration progress: {str(progress_error)}")

            # 更新shot状态为生成中
            try:
                shot_obj = db.query(Shot).filter(Shot.shot_id == shot.shot_id).first()
                if shot_obj:
                    shot_obj.video_status = "generating"
                    if not shot_obj.status_detail:
                        shot_obj.status_detail = {}
                    shot_obj.status_detail['video_status'] = 'generating'
                    shot_obj.status_detail['video_started_at'] = datetime.utcnow().isoformat()
                    flag_modified(shot_obj, 'status_detail')
                    db.commit()
            except Exception as update_error:
                logger.error(f"Failed to update shot status to generating: {str(update_error)}")

            freeze_record = None
            try:
                # 计算视频时长和积分
                shot_duration = shot.video_duration if shot.video_duration else 5
                if shot_duration <= 4:
                    video_duration = 4
                elif shot_duration <= 8:
                    video_duration = 8
                else:
                    video_duration = 12

                cost = ModelPrices.calculate_video_cost("sora2", video_duration)
                required_points = int(math.ceil(cost * 100))

                # 冻结积分
                freeze_record = PointsService.freeze_points(
                    db=db,
                    user_id=user_id,
                    points=required_points,
                    operation_type="generate_video",
                    creation_id=creation_id,
                    novel_id=creation.novel_id,
                    description=f"批量生成视频（{shot.title}）",
                    extra_data={
                        "shot_id": shot.shot_id,
                        "video_duration": video_duration,
                        "batch": True
                    }
                )

                # 生成视频 - 直接调用函数而不是delay
                # 包装在try-except中确保单个失败不影响其他
                try:
                    generate_single_shot_video_task(
                        shot_id=shot.shot_id,
                        creation_id=creation_id,
                        freeze_record_id=freeze_record.record_id
                    )
                    success_count += 1
                    logger.info(f"Video generation succeeded for shot {shot.shot_id}")

                    # 更新shot状态为完成
                    try:
                        shot_obj = db.query(Shot).filter(Shot.shot_id == shot.shot_id).first()
                        if shot_obj:
                            shot_obj.video_status = "completed"
                            if not shot_obj.status_detail:
                                shot_obj.status_detail = {}
                            shot_obj.status_detail['video_status'] = 'completed'
                            shot_obj.status_detail['video_completed_at'] = datetime.utcnow().isoformat()
                            flag_modified(shot_obj, 'status_detail')
                            db.commit()
                    except Exception as update_error:
                        logger.error(f"Failed to update shot status to completed: {str(update_error)}")

                    # 更新videoGeneration进度
                    try:
                        creation_refresh = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                        if creation_refresh and creation_refresh.extra_data and 'steps' in creation_refresh.extra_data:
                            if 'videoGeneration' in creation_refresh.extra_data['steps']:
                                creation_refresh.extra_data['steps']['videoGeneration']['progress']['completed'] += 1
                                creation_refresh.extra_data['steps']['videoGeneration']['progress']['success'] += 1
                                creation_refresh.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                                flag_modified(creation_refresh, 'extra_data')
                                db.commit()
                    except Exception as progress_error:
                        logger.error(f"Failed to update videoGeneration progress: {str(progress_error)}")

                except SoftTimeLimitExceeded as timeout_error:
                    # 单个视频生成超时（30分钟）
                    logger.error(f"Video generation timeout for shot {shot.shot_id} (exceeded 30 minutes)")

                    # 更新shot状态为失败
                    try:
                        shot_obj = db.query(Shot).filter(Shot.shot_id == shot.shot_id).first()
                        if shot_obj:
                            shot_obj.video_status = "failed"
                            if not shot_obj.status_detail:
                                shot_obj.status_detail = {}
                            shot_obj.status_detail['video_status'] = 'failed'
                            shot_obj.status_detail['video_error'] = '视频生成超时（超过30分钟），请重试'
                            shot_obj.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
                            flag_modified(shot_obj, 'status_detail')
                            db.commit()
                    except Exception as update_error:
                        logger.error(f"Failed to update shot status: {str(update_error)}")

                    # 释放冻结的积分
                    if freeze_record:
                        try:
                            PointsService.release_frozen_points(db, freeze_record.record_id, reason=f"视频生成超时")
                            logger.info(f"Released frozen points for shot {shot.shot_id}")
                        except Exception as release_error:
                            logger.error(f"Failed to release frozen points: {str(release_error)}")

                    failed_count += 1

                    # 更新videoGeneration进度
                    try:
                        creation_refresh = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                        if creation_refresh and creation_refresh.extra_data and 'steps' in creation_refresh.extra_data:
                            if 'videoGeneration' in creation_refresh.extra_data['steps']:
                                creation_refresh.extra_data['steps']['videoGeneration']['progress']['completed'] += 1
                                creation_refresh.extra_data['steps']['videoGeneration']['progress']['failed'] += 1
                                creation_refresh.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                                flag_modified(creation_refresh, 'extra_data')
                                db.commit()
                    except Exception as progress_error:
                        logger.error(f"Failed to update videoGeneration progress: {str(progress_error)}")

                    # 继续处理下一个shot，不抛出异常

                except Exception as gen_error:
                    # 视频生成失败，记录错误但继续处理下一个
                    logger.error(f"Video generation failed for shot {shot.shot_id}: {str(gen_error)}")
                    logger.error(traceback.format_exc())

                    # 更新shot状态为失败
                    try:
                        shot_obj = db.query(Shot).filter(Shot.shot_id == shot.shot_id).first()
                        if shot_obj:
                            shot_obj.video_status = "failed"
                            if not shot_obj.status_detail:
                                shot_obj.status_detail = {}
                            shot_obj.status_detail['video_status'] = 'failed'
                            shot_obj.status_detail['video_error'] = str(gen_error)
                            shot_obj.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
                            flag_modified(shot_obj, 'status_detail')
                            db.commit()
                    except Exception as update_error:
                        logger.error(f"Failed to update shot status: {str(update_error)}")

                    # 释放冻结的积分
                    if freeze_record:
                        try:
                            PointsService.release_frozen_points(db, freeze_record.record_id, reason=f"视频生成失败: {str(gen_error)}")
                            logger.info(f"Released frozen points for shot {shot.shot_id}")
                        except Exception as release_error:
                            logger.error(f"Failed to release frozen points: {str(release_error)}")

                    failed_count += 1

                    # 更新videoGeneration进度
                    try:
                        creation_refresh = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                        if creation_refresh and creation_refresh.extra_data and 'steps' in creation_refresh.extra_data:
                            if 'videoGeneration' in creation_refresh.extra_data['steps']:
                                creation_refresh.extra_data['steps']['videoGeneration']['progress']['completed'] += 1
                                creation_refresh.extra_data['steps']['videoGeneration']['progress']['failed'] += 1
                                creation_refresh.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                                flag_modified(creation_refresh, 'extra_data')
                                db.commit()
                    except Exception as progress_error:
                        logger.error(f"Failed to update videoGeneration progress: {str(progress_error)}")

                    # 继续处理下一个shot，不抛出异常

            except InsufficientPointsError as e:
                logger.error(f"Insufficient points for shot {shot.shot_id}: {str(e)}")

                # 更新shot状态为失败
                try:
                    shot_obj = db.query(Shot).filter(Shot.shot_id == shot.shot_id).first()
                    if shot_obj:
                        shot_obj.video_status = "failed"
                        if not shot_obj.status_detail:
                            shot_obj.status_detail = {}
                        shot_obj.status_detail['video_status'] = 'failed'
                        shot_obj.status_detail['video_error'] = f"积分不足: {str(e)}"
                        shot_obj.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
                        flag_modified(shot_obj, 'status_detail')
                        db.commit()
                except Exception as update_error:
                    logger.error(f"Failed to update shot status: {str(update_error)}")

                failed_count += 1

                # 更新videoGeneration进度
                try:
                    creation_refresh = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                    if creation_refresh and creation_refresh.extra_data and 'steps' in creation_refresh.extra_data:
                        if 'videoGeneration' in creation_refresh.extra_data['steps']:
                            creation_refresh.extra_data['steps']['videoGeneration']['progress']['completed'] += 1
                            creation_refresh.extra_data['steps']['videoGeneration']['progress']['failed'] += 1
                            creation_refresh.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                            flag_modified(creation_refresh, 'extra_data')
                            db.commit()
                except Exception as progress_error:
                    logger.error(f"Failed to update videoGeneration progress: {str(progress_error)}")

                break  # 积分不足，停止后续生成

            except Exception as e:
                logger.error(f"Failed to prepare video generation for shot {shot.shot_id}: {str(e)}")
                logger.error(traceback.format_exc())

                # 如果已经冻结了积分，需要释放
                if freeze_record:
                    try:
                        PointsService.release_frozen_points(db, freeze_record.record_id, reason=f"准备失败: {str(e)}")
                    except:
                        pass

                # 更新shot状态为失败
                try:
                    shot_obj = db.query(Shot).filter(Shot.shot_id == shot.shot_id).first()
                    if shot_obj:
                        shot_obj.video_status = "failed"
                        if not shot_obj.status_detail:
                            shot_obj.status_detail = {}
                        shot_obj.status_detail['video_status'] = 'failed'
                        shot_obj.status_detail['video_error'] = str(e)
                        shot_obj.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
                        flag_modified(shot_obj, 'status_detail')
                        db.commit()
                except Exception as update_error:
                    logger.error(f"Failed to update shot status: {str(update_error)}")

                failed_count += 1

                # 更新videoGeneration进度
                try:
                    creation_refresh = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                    if creation_refresh and creation_refresh.extra_data and 'steps' in creation_refresh.extra_data:
                        if 'videoGeneration' in creation_refresh.extra_data['steps']:
                            creation_refresh.extra_data['steps']['videoGeneration']['progress']['completed'] += 1
                            creation_refresh.extra_data['steps']['videoGeneration']['progress']['failed'] += 1
                            creation_refresh.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                            flag_modified(creation_refresh, 'extra_data')
                            db.commit()
                except Exception as progress_error:
                    logger.error(f"Failed to update videoGeneration progress: {str(progress_error)}")

                # 继续处理下一个shot

        # 批量生成完成，更新videoGeneration状态为success
        try:
            creation_final = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation_final and creation_final.extra_data and 'steps' in creation_final.extra_data:
                if 'videoGeneration' in creation_final.extra_data['steps']:
                    creation_final.extra_data['steps']['videoGeneration']['status'] = 'success'
                    creation_final.extra_data['steps']['videoGeneration']['progress']['current_shot_id'] = None
                    creation_final.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                    flag_modified(creation_final, 'extra_data')
                    db.commit()
                    logger.info(f"Updated videoGeneration status to success")
        except Exception as final_error:
            logger.error(f"Failed to update final videoGeneration status: {str(final_error)}")

        logger.info(f"Batch video generation completed: {success_count} succeeded, {failed_count} failed, {skipped_count} skipped")

        return {
            "status": "completed",
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "total": len(all_shots)
        }

    except Exception as e:
        logger.error(f"Error in batch video generation: {str(e)}")
        logger.error(traceback.format_exc())

        # 更新videoGeneration状态为failed
        try:
            creation_error = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation_error and creation_error.extra_data and 'steps' in creation_error.extra_data:
                if 'videoGeneration' in creation_error.extra_data['steps']:
                    creation_error.extra_data['steps']['videoGeneration']['status'] = 'failed'
                    creation_error.extra_data['steps']['videoGeneration']['error'] = str(e)
                    creation_error.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                    flag_modified(creation_error, 'extra_data')
                    db.commit()
        except Exception as update_error:
            logger.error(f"Failed to update videoGeneration to failed status: {str(update_error)}")

        raise
    finally:
        db.close()
