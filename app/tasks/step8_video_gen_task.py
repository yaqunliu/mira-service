"""
V2 视频生成流程 - 步骤 8: AI 视频生成
"""
import os
import json
from typing import Dict, Any, List

from app.core.celery_app import celery_app
from app.core.logger import logger
from app.db.base import _get_sync_session_factory
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.models.creation import Creation
from app.models.shot import Shot
from app.models.scene import Scene
from app.utils.task_types import TaskType
from app.utils.ai_client import AIClient
from app.utils.us3 import US3Client
from app.utils.local_storage import get_storage_client
from app.utils.points_deduction import deduct_points_for_video
from app.utils.ffmpeg_utils import FFmpegUtils
from app.models.user import User
import tempfile
import requests

@celery_app.task(
    bind=True, 
    name="generate_scene_videos_task",
    autoretry_for=(Exception,),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True
)
def generate_scene_videos_task(self, scene_id: int, creation_id: int):
    """
    场景视频生成任务（生成场景下所有分镜的视频）
    """
    db: Session = _get_sync_session_factory()()
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
        us3_client = get_storage_client()

        # 获取作品配置的模型
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        video_model = (creation.extra_data or {}).get('video_model', 'doubao-seedance-1-5-pro-251215')
        
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

                logger.info(f"Regenerating video for shot {shot.shot_id} in scene {scene_id} using model {video_model}")

                # 根据模型选择时长映射
                shot_duration = shot.video_duration if shot.video_duration else 5  # 默认5秒
                if video_model == "Wan-AI/Wan2.6-I2V":
                    if shot_duration <= 5:
                        video_duration = 5
                    elif shot_duration <= 10:
                        video_duration = 10
                    else:
                        video_duration = 15
                elif video_model in ["viduq2-pro", "viduq2-turbo"]:
                    video_duration = min(max(int(shot_duration), 1), 10)
                elif video_model == "doubao-seedance-1-5-pro-251215":
                    video_duration = 5
                else:
                    # Sora2 支持 4/8/12秒
                    if shot_duration <= 4:
                        video_duration = 4
                    elif shot_duration <= 8:
                        video_duration = 8
                    else:
                        video_duration = 12

                logger.info(f"Shot时长: {shot_duration}秒，选择时长: {video_duration}秒")

                # 调用对应的视频生成 API
                try:
                    if video_model == "Wan-AI/Wan2.6-I2V":
                        resolution = (shot.extra_data or {}).get('video_resolution', '1080P')
                        video_url = ai_client.generate_video_by_image_wan_ai(
                            image_url=shot.image_url,
                            prompt=video_prompt,
                            duration=video_duration,
                            resolution=resolution
                        )
                    elif video_model in ["viduq2-pro", "viduq2-turbo"]:
                        resolution = (shot.extra_data or {}).get('video_resolution', '1080p').lower()
                        video_url = ai_client.generate_video_by_image_vidu(
                            image_url=shot.image_url,
                            prompt=video_prompt,
                            duration=video_duration,
                            resolution=resolution,
                            model=video_model
                        )
                    elif video_model == "doubao-seedance-1-5-pro-251215":
                        # 优先从 shot 获取比例，如果没有则从 creation 获取
                        aspect_ratio = (shot.extra_data or {}).get('aspect_ratio')
                        if not aspect_ratio and creation:
                            aspect_ratio = (creation.extra_data or {}).get('aspect_ratio')
                        if not aspect_ratio:
                            aspect_ratio = '16:9'
                            
                        resolution = (shot.extra_data or {}).get('video_resolution', '720p').lower()
                        video_url = ai_client.generate_video_by_image_doubao_modelverse(
                            image_url=shot.image_url,
                            prompt=video_prompt,
                            duration=video_duration,
                            aspect_ratio=aspect_ratio,
                            resolution=resolution
                        )
                    else:
                        video_url = ai_client.generate_video_by_image_sora2(
                            image_url=shot.image_url,
                            prompt=video_prompt,
                            duration=video_duration
                        )
                except Exception as api_error:
                    # 如果 API 调用失败（包括轮询发现 Failure），立即更新状态并抛出
                    logger.error(f"API 调用失败: shot_id={shot.shot_id}, error={str(api_error)}")
                    shot.video_status = "failed"
                    if not shot.status_detail:
                        shot.status_detail = {}
                    shot.status_detail['video_status'] = 'failed'
                    shot.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
                    shot.status_detail['video_error'] = str(api_error)
                    flag_modified(shot, 'status_detail')
                    
                    # 更新步骤状态为失败
                    try:
                        from app.services.creation_service import CreationService
                        CreationService.update_creation_step_status(
                            db=db,
                            creation_id=creation_id,
                            step_name="videoGeneration",
                            status="failed",
                            commit=False
                        )
                        # 清除任务 ID
                        if creation:
                            creation.current_task_id = None
                    except:
                        pass
                        
                    db.commit()
                    raise api_error

                # 下载视频到临时文件
                temp_video_fd, temp_video_path = tempfile.mkstemp(suffix='.mp4')
                os.close(temp_video_fd)

                try:
                    logger.info(f"下载视频: {video_url}")
                    response = requests.get(video_url, timeout=300)
                    response.raise_for_status()
                    with open(temp_video_path, 'wb') as f:
                        f.write(response.content)

                    # 标准化视频：统一分辨率、帧率、编码参数
                    # 提高视频清晰度：使用 CRF=18 和 Lanczos 高质量采样
                    logger.info(f"标准化视频: shot_id={shot.shot_id}, model={video_model}")
                    normalized_video_path = temp_video_path.replace(".mp4", "_normalized.mp4")
                    
                    # 只有 Sora 和 Doubao 会生成音频，其他模型生成的是静音视频
                    has_audio_model = video_model not in ["Wan-AI/Wan2.6-I2V", "viduq2-pro", "viduq2-turbo"]
                    
                    # 如果 separate_audio=False，不分离音频
                    if separate_audio is False:
                        has_audio_model = False
                    
                    if FFmpegUtils.normalize_video(temp_video_path, normalized_video_path, duration=float(video_duration), remove_audio=not has_audio_model):
                        if has_audio_model:
                            # 分离音视频 (使用标准化后的视频)
                            logger.info(f"分离音视频: shot_id={shot.shot_id}")
                            silent_video_path, audio_path = FFmpegUtils.separate_audio_video(normalized_video_path)
                        else:
                            # 非音频模型，标准化后的视频即为静音视频，无音频文件
                            logger.info(f"非音频模型，跳过分离: shot_id={shot.shot_id}")
                            silent_video_path = normalized_video_path
                            audio_path = None
                        
                        # 清理标准化后的临时视频 (如果是音频模型，已经通过 separate_audio_video 复制/处理到了 silent_video_path)
                        # 如果是非音频模型，silent_video_path 就是 normalized_video_path，所以不能在这里删除
                        if has_audio_model:
                            try:
                                if os.path.exists(normalized_video_path):
                                    os.remove(normalized_video_path)
                            except:
                                pass
                    else:
                        # 如果标准化失败，降级使用原始视频
                        logger.warning(f"视频标准化失败，降级使用原始视频: shot_id={shot.shot_id}")
                        if has_audio_model:
                            silent_video_path, audio_path = FFmpegUtils.separate_audio_video(temp_video_path)
                        else:
                            silent_video_path = temp_video_path
                            audio_path = None

                    # 上传静音视频到US3
                    # 注意：第二个位置参数是 bucket 而非 put_key，必须用关键字传参，
                    # 否则文件名会退化成临时文件名；upload_file 返回的是结果字典，
                    # 需要经 get_file_url 转成 URL 再落库（对齐本文件 766 行的写法）。
                    video_filename = f"videos/{creation_id}/{shot.shot_id}_{uuid.uuid4().hex[:8]}_silent.mp4"
                    video_upload_result = us3_client.upload_file(silent_video_path, put_key=video_filename)
                    if not video_upload_result.get('success'):
                        raise Exception(f"视频上传失败: {video_upload_result.get('message')}")
                    silent_video_url = us3_client.get_file_url(video_upload_result['key'])
                    logger.info(f"静音视频上传成功: {silent_video_url}")

                    # 上传音频到US3（如果有音频）
                    audio_url = None
                    if audio_path and os.path.exists(audio_path):
                        audio_filename = f"audio/{creation_id}/{shot.shot_id}_{uuid.uuid4().hex[:8]}.mp3"
                        audio_upload_result = us3_client.upload_file(audio_path, put_key=audio_filename)
                        if audio_upload_result.get('success'):
                            audio_url = us3_client.get_file_url(audio_upload_result['key'])
                            logger.info(f"音频上传成功: {audio_url}")
                        else:
                            logger.error(f"音频上传失败: {audio_upload_result.get('message')}")
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

                    # 记录版本历史
                    if not shot.extra_data:
                        shot.extra_data = {}
                    if 'version_history' not in shot.extra_data:
                        shot.extra_data['version_history'] = []
                    
                    shot.extra_data['version_history'].append({
                        'version_id': str(uuid.uuid4()),
                        'video_url': silent_video_url,
                        'audio_url': audio_url,
                        'video_duration': float(video_duration),
                        'video_model': video_model,
                        'created_at': datetime.utcnow().isoformat()
                    })
                    flag_modified(shot, 'extra_data')

                    # 保存视频版本历史到 status_detail
                    from datetime import datetime
                    if not shot.status_detail:
                        shot.status_detail = {}
                    if 'video_historys' not in shot.status_detail:
                        shot.status_detail['video_historys'] = []
                    
                    shot.status_detail['video_historys'].append({
                        'image_url': silent_video_url,
                        'audio_url': audio_url,
                        'video_prompt': video_prompt,
                        'video_model': video_model,
                        'created_at': datetime.utcnow().isoformat()
                    })
                    flag_modified(shot, 'status_detail')

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
                    # 获取分辨率配置
                    if video_model in ["viduq2-pro", "viduq2-turbo", "doubao-seedance-1-5-pro-251215"]:
                        resolution = (shot.extra_data or {}).get('video_resolution', '1080p').lower()
                    else:
                        resolution = "720p"

                    deduct_points_for_video(
                        db=db,
                        user_id=creation.owner_id,
                        model_name=video_model,
                        duration_seconds=video_duration,
                        resolution=resolution,
                        creation_id=creation_id,
                        novel_id=scene.novel_id,
                        shot_id=shot.shot_id
                    )
                    logger.info(f"视频生成积分扣除成功: shot_id={shot.shot_id}")
                except Exception as points_error:
                    logger.error(f"视频生成积分扣除失败: {str(points_error)}")
                    # 积分扣除失败不影响视频生成，记录错误后继续
                db.flush()
                db.commit()  # 提交当前分镜的更改，确保 version_history 被保存
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
                flag_modified(shot, 'status_detail')

                # 更新 extra_data 状态
                if not shot.extra_data:
                    shot.extra_data = {}
                shot.extra_data['video_generation_status'] = 'failed'
                flag_modified(shot, 'extra_data')
                
                db.commit()
                logger.info(f"Shot {shot.shot_id} 视频生成失败状态已实时保存到数据库")

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


@celery_app.task(
    bind=True, 
    name="generate_single_shot_video_task", 
    soft_time_limit=3600, 
    time_limit=3700,
    autoretry_for=(Exception,),
    retry_backoff=60,
    max_retries=3
)
def generate_single_shot_video_task(self, shot_id: int, creation_id: int, freeze_record_id: int = None, model_name: str = None, last_frame_image_url: str = None, separate_audio: bool = None):
    """
    单个分镜视频生成任务

    时间限制：
    - soft_time_limit: 3600秒 (1小时) - 超时后抛出SoftTimeLimitExceeded异常
    - time_limit: 3700秒 (约1小时) - 硬性终止任务

    Args:
        shot_id: 分镜ID
        creation_id: 作品ID
        freeze_record_id: 积分冻结记录ID（用于后续扣除）
        model_name: 使用的模型名称
        last_frame_image_url: 尾帧图片URL（可选）
    """
    logger.info(f"开始分镜视频生成任务: shot_id={shot_id}, creation_id={creation_id}, model_name={model_name}, 有尾帧: {bool(last_frame_image_url)}, separate_audio={separate_audio}")
    db: Session = _get_sync_session_factory()()

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
        us3_client = get_storage_client()

        # 检查是否有 video_prompt，优先使用 extra_data 中的 video_prompt
        # 只有在 video_prompt 为空、或者是降级提示词时才重新生成
        video_prompt = (shot.extra_data or {}).get("video_prompt")
        
        # 用户需求：如果有 video_prompt 且不为空，就不需要再次生成提示词，直接用提示词生成视频
        # force_regen 现在默认为 False，只有在没有有效提示词时才进行生成
        force_regen = False 

        if not video_prompt or force_regen:
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
            
            # V5：获取首尾帧提示词
            shot_extra_data = shot.extra_data or {}
            start_frame_prompt = image_prompt  # 首帧提示词
            end_frame_prompt = shot_extra_data.get("end_frame_image_prompt")  # 尾帧提示词
            
            logger.info(f"Shot {shot_id} (step8) 首尾帧提示词: start_frame={len(start_frame_prompt) if start_frame_prompt else 0}字, end_frame={len(end_frame_prompt) if end_frame_prompt else 0}字")

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

            # 获取关联的角色信息
            characters = []
            if hasattr(shot, 'characters') and shot.characters:
                for char in shot.characters:
                    # 组合外观描述
                    appearance_parts = []
                    if char.appearance:
                        appearance_parts.append(char.appearance)
                    if char.clothing:
                        appearance_parts.append(f"穿着{char.clothing}")
                    if char.hair:
                        appearance_parts.append(f"发型：{char.hair}")

                    appearance_full = '，'.join(appearance_parts) if appearance_parts else ''

                    # 年龄段与外观状态直接读结构化字段
                    # （改造前 age_group 恒为 '未知'，见 en-plan.md Phase 3.5.5）
                    characters.append({
                        'name': char.name,
                        'age_group': char.age_group,
                        'state': char.state,
                        'appearance': appearance_full,
                        'identity': char.variant_label,
                    })

                    logger.info(f"角色识别: {char.name} -> {char.variant_label}")

            # 从creation获取模型配置
            extra_data = creation.extra_data or {} if creation else {}
            llm_model = extra_data.get('llm_model')
            text_to_image_model = extra_data.get('text_to_image_model')
            image_to_image_model = extra_data.get('image_to_image_model')

            # 生成video_prompt - 使用独立的提示词生成函数（V5版本）
            from app.utils.video_prompt_generator import generate_video_prompt
            prompt_result = generate_video_prompt(
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
            shot.extra_data['video_prompt'] = video_prompt
            shot.extra_data['cut_method'] = cut_method
            shot.extra_data['cut_reason'] = cut_reason
            shot.extra_data['video_prompt_status'] = 'completed'
            flag_modified(shot, 'extra_data')
            db.commit()
            logger.info(f"Generated video prompt for shot {shot.shot_id}: {video_prompt[:100]}...")
            logger.info(f"Cut method: {cut_method}, reason: {cut_reason}")

        logger.info(f"Generating video for shot {shot.shot_id}")

        # 获取分镜时长
        shot_duration = shot.video_duration if shot.video_duration else 5

        # 根据作品配置或默认选择视频生成模型
        video_model = model_name or (creation.extra_data or {}).get('video_model', 'doubao-seedance-1-5-pro-251215') if creation else (model_name or 'doubao-seedance-1-5-pro-251215')
        
        # 根据模型选择时长映射
        if video_model == "Wan-AI/Wan2.6-I2V":
            # Wan-AI 支持 5/10/15秒
            if shot_duration <= 5:
                video_duration = 5
            elif shot_duration <= 10:
                video_duration = 10
            else:
                video_duration = 15
        elif video_model in ["viduq2-pro", "viduq2-turbo"]:
            # Vidu 支持 1-10秒
            video_duration = min(max(int(shot_duration), 1), 10)
        elif "doubao" in video_model:
            # 火山 Seedance 1.5 Pro 支持 4-12 秒
            video_duration = min(max(int(shot_duration), 4), 12)
        else:
            # Sora2 支持 4/8/12秒
            if shot_duration <= 4:
                video_duration = 4
            elif shot_duration <= 8:
                video_duration = 8
            else:
                video_duration = 12

        logger.info(f"Shot时长: {shot_duration}秒，模型: {video_model}, 选择时长: {video_duration}秒")

        # 调用对应的视频生成 API
        try:
            if video_model == "Wan-AI/Wan2.6-I2V":
                # 获取分辨率配置，默认为 1080P
                resolution = (shot.extra_data or {}).get('video_resolution', '1080P')
                video_url = ai_client.generate_video_by_image_wan_ai(
                    image_url=shot.image_url,
                    prompt=video_prompt,
                    duration=video_duration,
                    resolution=resolution,
                    last_frame_image_url=last_frame_image_url
                )
            elif video_model in ["viduq2-pro", "viduq2-turbo", "viduq3-pro"]:
                # 获取分辨率配置，默认为 1080p (注意 Vidu 是小写)
                resolution = (shot.extra_data or {}).get('video_resolution', '1080p').lower()
                video_url = ai_client.generate_video_by_image_vidu(
                    image_url=shot.image_url,
                    prompt=video_prompt,
                    duration=video_duration,
                    resolution=resolution,
                    model=video_model,
                    last_frame_image_url=last_frame_image_url
                )
            elif "doubao" in video_model:
                # 获取分辨率和比例配置
                aspect_ratio = (shot.extra_data or {}).get('aspect_ratio', '16:9')
                resolution = (shot.extra_data or {}).get('video_resolution', '720p').lower()
                video_url = ai_client.generate_video_by_image_doubao_modelverse(
                    image_url=shot.image_url,
                    prompt=video_prompt,
                    duration=video_duration,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    last_frame_image_url=last_frame_image_url
                )
            elif video_model.startswith("veo"):
                video_url = ai_client.generate_video_by_image_veo(
                    image_url=shot.image_url,
                    prompt=video_prompt,
                    duration=video_duration,
                )
            else:
                # 调用 Sora2 图生视频 API（size参数留空使用API默认值）
                video_url = ai_client.generate_video_by_image_sora2(
                    image_url=shot.image_url,
                    prompt=video_prompt,
                    duration=video_duration
                )
        except Exception as api_error:
            # 如果 API 调用失败（包括轮询发现 Failure），立即更新状态并抛出
            logger.error(f"API 调用失败: shot_id={shot.shot_id}, error={str(api_error)}")
            shot.video_status = "failed"
            if not shot.status_detail:
                shot.status_detail = {}
            shot.status_detail['video_status'] = 'failed'
            shot.status_detail['video_updated_at'] = datetime.utcnow().isoformat()
            shot.status_detail['video_error'] = str(api_error)
            flag_modified(shot, 'status_detail')
            db.commit()
            raise api_error

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

            # 分离音视频（如果 separate_audio 不为 False）
            if separate_audio is not False:
                logger.info(f"分离音视频: shot_id={shot.shot_id}")
                silent_video_path, audio_path = FFmpegUtils.separate_audio_video(temp_video_path)
                video_filename = f"videos/{creation_id}/{shot.shot_id}_{uuid.uuid4().hex[:8]}_silent.mp4"
            else:
                logger.info(f"不分离音视频: shot_id={shot.shot_id}")
                silent_video_path = temp_video_path
                audio_path = None
                video_filename = f"videos/{creation_id}/{shot.shot_id}_{uuid.uuid4().hex[:8]}.mp4"

            # 上传视频到US3
            video_put_key = video_filename
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

            # 记录版本历史
            if not shot.extra_data:
                shot.extra_data = {}
            if 'version_history' not in shot.extra_data:
                shot.extra_data['version_history'] = []
            
            shot.extra_data['version_history'].append({
                'version_id': str(uuid.uuid4()),
                'video_url': silent_video_url,
                'audio_url': audio_url,
                'video_duration': float(video_duration),
                'video_model': video_model,
                'created_at': datetime.utcnow().isoformat()
            })
            flag_modified(shot, 'extra_data')

            # 保存视频版本历史到 status_detail
            if not shot.status_detail:
                shot.status_detail = {}
            if 'video_historys' not in shot.status_detail:
                shot.status_detail['video_historys'] = []
            
            shot.status_detail['video_historys'].append({
                'image_url': silent_video_url,
                'audio_url': audio_url,
                'video_prompt': video_prompt,
                'video_model': video_model,
                'created_at': datetime.utcnow().isoformat()
            })
            flag_modified(shot, 'status_detail')

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

                # 清除 creation 的 current_task_id
                creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                if creation:
                    creation.current_task_id = None

                db.commit()
                logger.info(f"Shot {shot_id} video_status 和 status_detail 已更新为 failed，并清除了 current_task_id")
        except Exception as update_error:
            logger.error(f"Failed to update shot status to failed: {str(update_error)}")
        raise e
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_all_videos_task", soft_time_limit=10800, time_limit=10900)
def generate_all_videos_task(self, creation_id: int, user_id: int):
    """
    为作品中所有分镜批量生成视频

    时间限制：
    - soft_time_limit: 10800秒 (3小时) - 超时后抛出SoftTimeLimitExceeded异常
    - time_limit: 10900秒 (约3小时) - 硬性终止任务

    流程：
    1. 检查每个shot是否有video_prompt，没有则先生成
    2. 逐个生成视频
    """
    db: Session = _get_sync_session_factory()()
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

            # 第一步：确保该shot有video_prompt（优先使用已有的，如果没有或者是降级提示词则生成）
            video_prompt = (shot.extra_data or {}).get('video_prompt') if shot.extra_data else None
            if not video_prompt:
                logger.info(f"Generating/Regenerating video_prompt for shot {shot.shot_id}")
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
                
                # 获取视频模型和分辨率
                video_model = (creation.extra_data or {}).get('video_model', 'sora2')
                video_resolution = (shot.extra_data or {}).get('video_resolution', '1080P')
                
                # 根据模型选择时长映射
                if video_model == "Wan-AI/Wan2.6-I2V":
                    if shot_duration <= 5:
                        video_duration = 5
                    elif shot_duration <= 10:
                        video_duration = 10
                    else:
                        video_duration = 15
                    # Wan-AI 使用分辨率计费 (720p/1080p)
                    cost = ModelPrices.calculate_video_cost(video_model, video_duration, video_resolution.lower())
                elif video_model == "doubao-seedance-1-5-pro-251215":
                    video_duration = 5
                    # 使用 1080p 计费
                    cost = ModelPrices.calculate_video_cost(video_model, video_duration, "1080p")
                else:
                    if shot_duration <= 4:
                        video_duration = 4
                    elif shot_duration <= 8:
                        video_duration = 8
                    else:
                        video_duration = 12
                    # Sora2 默认 720p 计费
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
                        "video_model": video_model,
                        "video_resolution": video_resolution,
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
            if creation_final:
                if creation_final.extra_data and 'steps' in creation_final.extra_data:
                    if 'videoGeneration' in creation_final.extra_data['steps']:
                        creation_final.extra_data['steps']['videoGeneration']['status'] = 'success'
                        creation_final.extra_data['steps']['videoGeneration']['progress']['current_shot_id'] = None
                        creation_final.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                        flag_modified(creation_final, 'extra_data')
                
                # 清除任务 ID
                creation_final.current_task_id = None
                db.commit()
                logger.info(f"Updated videoGeneration status to success and cleared current_task_id")
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
            if creation_error:
                if creation_error.extra_data and 'steps' in creation_error.extra_data:
                    if 'videoGeneration' in creation_error.extra_data['steps']:
                        creation_error.extra_data['steps']['videoGeneration']['status'] = 'failed'
                        creation_error.extra_data['steps']['videoGeneration']['error'] = str(e)
                        creation_error.extra_data['steps']['videoGeneration']['updatedAt'] = int(datetime.utcnow().timestamp())
                        flag_modified(creation_error, 'extra_data')
                
                # 清除任务 ID
                creation_error.current_task_id = None
                db.commit()
                logger.info(f"Updated videoGeneration status to failed and cleared current_task_id")
        except Exception as update_error:
            logger.error(f"Failed to update videoGeneration to failed status: {str(update_error)}")

        raise
    finally:
        db.close()
