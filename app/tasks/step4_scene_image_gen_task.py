"""
V2 视频生成流程 - 步骤 4: 场景图生成
"""
import os
import json
import httpx
from datetime import datetime
from app.core.celery_app import celery_app
from app.core.logger import logger
from app.db.base import _get_sync_session_factory
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from app.models.creation import Creation
from app.models.scene import Scene
from app.utils.task_types import TaskType
from app.utils.ai_client import AIClient
from app.utils.file_utils import read_prompt_file
from app.utils.us3 import US3Client
from app.utils.local_storage import get_storage_client
from app.utils.upload_helper import upload_helper
from app.core.config import settings
from app.models.user import User
from app.utils.points_deduction import deduct_points_for_image
from app.utils.model_prices import ModelPrices
from app.services.model_config_service import ModelConfigService
import math

# 风格映射
STYLE_MAPPING = {
    "realism": "写实摄影,摄影作品，真实的光影和材质，逼真的场景细节",
    "cyberpunk": "赛博朋克风格，霓虹灯效果，高科技与低生活的结合，未来主义",
    "ukiyoe": "浮世绘风格，传统日本绘画风格，平面化，鲜明的色彩",
    "watercolor": "水彩画风格，柔和的色彩过渡，透明感，自然的笔触",
    "anime": "日漫风格，典型的日本动画美学，夸张的场景元素"
}


@celery_app.task(bind=True, name="batch_generate_scene_images_task")
def batch_generate_scene_images_task(self, creation_id: int, force_regenerate: bool = False):
    """
    批量生成场景图片任务（并行）
    """
    db: Session = _get_sync_session_factory()()
    try:
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_IMAGE_GENERATION,
                'creation_id': creation_id,
                'status': '正在准备批量生成场景图片...'
            }
        )

        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if not creation:
            raise Exception(f"Creation not found: {creation_id}")

        # Update Step Status: Processing
        from app.services.creation_service import CreationService
        CreationService.update_creation_step_status(
            db=db,
            creation_id=creation_id,
            step_name="sceneImageGeneration",
            status="processing",
            task_id=self.request.id
        )

        # 走统一入口：兼容跨章节复用的场景（其 creation_id 指向原创作）
        scenes = CreationService.get_creation_scenes(db, creation)
        if not scenes:
            # 查不到场景说明前置步骤没跑通，必须失败。以前这里标记 success 直接返回，
            # 问题会一路静默滑到分镜拆解才暴露。
            raise Exception("未找到场景数据，请先进行场景分析")

        # 筛选需要生成的场景
        scenes_to_generate = []
        for scene in scenes:
            if force_regenerate or not scene.image_url:
                scenes_to_generate.append(scene.scene_id)

        if not scenes_to_generate:
            # Update Step Status: Success (Nothing to do)
            CreationService.update_creation_step_status(
                db=db,
                creation_id=creation_id,
                step_name="sceneImageGeneration",
                status="success"
            )
            return {"status": "success", "message": "All scenes have images"}

        logger.info(f"Starting batch generation for {len(scenes_to_generate)} scenes")

        # 使用 Celery group 并行执行
        from celery import group
        job = group(
            generate_single_scene_image_task.s(scene_id, creation_id) 
            for scene_id in scenes_to_generate
        )
        result = job.apply_async()
        
        # 等待所有子任务完成 (设置较长的超时时间，例如 10 分钟)
        # 注意：这里会阻塞 Worker 线程，确保有足够的并发 Worker
        try:
            # 使用 disable_sync_subtasks=False 允许在任务中等待子任务，但这不是最佳实践
            # 更好的方式是使用 chord 或 chain，但为了保持现有逻辑简单，我们使用 allow_join_result
            # 或者简单地不等待结果，而是让前端轮询 creation 状态。
            # 但为了更新 creation 状态为 success，我们需要知道什么时候结束。
            
            # 修正：不要在任务中直接调用 result.get()，这会导致死锁或 RuntimeError
            # 替代方案：
            # 1. 使用 chord(header)(callback) 模式
            # 2. 或者让这个任务只是触发 group，然后立即返回。状态更新由回调任务处理。
            # 3. 或者使用 allow_join_result 上下文管理器（不推荐，但能解决报错）
            
            from celery.result import allow_join_result
            with allow_join_result():
                result.get(timeout=600)
            
            # Update Step Status: Success
            CreationService.update_creation_step_status(
                db=db,
                creation_id=creation_id,
                step_name="sceneImageGeneration",
                status="success"
            )
            
            # 清除 current_task_id
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                db.commit()

        except Exception as e:
            logger.warning(f"Batch generation timed out or failed: {e}")
            # 即使超时，也可能部分成功，但为了状态一致性，这里标记为 failed 或者 partial?
            # 暂时标记为 failed，让前端可以重试
            CreationService.update_creation_step_status(
                db=db,
                creation_id=creation_id,
                step_name="sceneImageGeneration",
                status="failed",
                error=str(e)
            )
            raise e
        
        return {
            "status": "success",
            "scene_count": len(scenes_to_generate)
        }

    except Exception as e:
        logger.error(f"Batch Scene Image Generation Failed: {str(e)}")
        # Update Step Status: Failed (Outer try-except)
        try:
            db.rollback() # Rollback any pending transaction first
            
            from app.services.creation_service import CreationService
            CreationService.update_creation_step_status(
                db=db,
                creation_id=creation_id,
                step_name="sceneImageGeneration",
                status="failed",
                error=str(e)
            )
            
            # 清除 current_task_id
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.current_task_id = None
                db.commit()
        except Exception as update_error:
            logger.error(f"Failed to update creation status: {update_error}")
            
        raise e
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_single_scene_image_task")
def generate_single_scene_image_task(self, scene_id: int, creation_id: int, model_name: str = None):
    """
    单个场景图片生成任务
    """
    import time
    task_start_time = time.perf_counter()
    db: Session = _get_sync_session_factory()()
    try:
        self.update_state(
            state='PROGRESS',
            meta={
                'task_type': TaskType.SCENE_IMAGE_GENERATION,
                'scene_id': scene_id,
                'creation_id': creation_id,
                'status': '正在生成场景图片...'
            }
        )

        scene = db.query(Scene).filter(Scene.scene_id == scene_id).first()
        if not scene:
            raise Exception(f"Scene not found: {scene_id}")

        # 从创作配置中获取模型配置和风格
        creation = scene.creation
        extra_data = creation.extra_data or {} if creation else {}
        text_to_image_model = ModelConfigService.resolve_model(
            "text_to_image",
            model_name,
            extra_data.get("text_to_image_model"),
            settings.IMAGE_MODEL_TEXT_TO_IMAGE,
            settings.IMAGE_MODEL_NAME,
        )
        llm_model = extra_data.get("llm_model") or settings.LLM_MODEL_NAME
        visual_style = extra_data.get("visual_style", extra_data.get("style", "anime"))

        # 获取风格描述
        style_description = STYLE_MAPPING.get(visual_style, STYLE_MAPPING["anime"])

        ai_client = AIClient(llm_model_name=llm_model, text_to_image_model=text_to_image_model)
        us3_client = get_storage_client()
        logger.info(f"Regenerating image for scene: {scene.title}, style: {visual_style}")

        # 优先从 extra_data 获取
        image_prompt = None
        if scene.extra_data and isinstance(scene.extra_data, dict):
            image_prompt = scene.extra_data.get("image_prompt")
            
        if image_prompt:
            pass # 已经获取到
        else:
            # 1. 获取图片提示词
            # V2 场景图生成逻辑：包含第一个分镜的信息
            from app.models.shot import Shot
            from app.models.character import Character
            
            # 获取该场景的第一个分镜
            first_shot = db.query(Shot).filter(Shot.scene_id == scene_id).order_by(Shot.shot_number.asc()).first()
            
            character_profiles = []
            current_shot_desc = "无"
            if first_shot:
                current_shot_desc = first_shot.description
                # 获取该分镜中的角色档案
                for char in first_shot.characters:
                    profile = f"{char.name}：{char.appearance or char.basic_info or '无描述'}"
                    character_profiles.append(profile)

            # 加载 V2 模板
            prompt_template = read_prompt_file("scene_image.md")
            
            # 构建环境设定描述
            # space_type 现在是 indoor/outdoor 枚举，布局细节在 extra_data.space_description
            scene_extra = scene.extra_data or {}
            env_config = {
                "时间": scene.time_setting,
                "地点": scene.location,
                "空间": scene_extra.get("space_description") or scene.space_type,
                "氛围": scene.atmosphere
            }
            environment_desc = json.dumps(env_config, ensure_ascii=False, indent=2)
            
            # 替换模板中的占位符
            system_prompt = prompt_template.replace("{{SCENE_ENVIRONMENT}}", environment_desc)
            system_prompt = system_prompt.replace("{{VISUAL_STYLE}}", style_description)
            system_prompt = system_prompt.replace("{character_profiles}", "\n".join(character_profiles) if character_profiles else "无")
            system_prompt = system_prompt.replace("{previous_shot}", "无") # 场景建立图通常没有上一分镜
            system_prompt = system_prompt.replace("{current_shot}", current_shot_desc)
            system_prompt = system_prompt.replace("{output_language}", "中文")
            
            messages = [
                {
                    "role": "user",
                    "content": f"{system_prompt}\n\n场景标题：{scene.title}\n视觉风格：{style_description}"
                }
            ]
            logger.info(f"Scene image generation V2 messages: {messages[0]['content']}")
            
            response = ai_client.chat_completion(messages=messages)
            image_prompt = response.get("content", "").strip()
            image_prompt = image_prompt.replace("```", "").strip()
            
            # 保存生成的提示词到 extra_data
            if scene.extra_data is None:
                scene.extra_data = {}
            scene.extra_data["image_prompt"] = image_prompt
            flag_modified(scene, "extra_data")

        # 2. 生成图片
        # 根据创作比例确定图片尺寸
        # 场景图统一使用 16:9 尺寸，不受全局 aspect_ratio 设置影响
        image_size = "1536x864"

        # 将风格描述添加到最终提示词中
        final_prompt = f"{image_prompt} {style_description}"

        logger.info(f"生成场景图片，固定使用 16:9 尺寸: {image_size}")
        logger.info(f"场景图片最终提示词: {final_prompt}")
        
        temp_image_url = ai_client.generate_image_by_prompt(
            prompt=final_prompt,
            model=ai_client.text_to_image_model,
            aspectRatio=image_size
        )
        
        # 3. 上传 US3
        import uuid
        filename = f"scenes/{creation_id}/{scene.scene_id}_{uuid.uuid4().hex[:8]}.png"
        
        # 处理图片下载（支持 local:// 协议）
        image_data = None
        if temp_image_url.startswith("local://"):
            # 读取本地文件
            temp_file_path = temp_image_url.replace("local://", "")
            logger.info(f"使用本地文件路径: {temp_file_path}")
            if not os.path.exists(temp_file_path):
                raise Exception(f"本地文件不存在: {temp_file_path}")
            with open(temp_file_path, 'rb') as f:
                image_data = f.read()
            logger.info(f"本地图像读取成功，大小: {len(image_data)} 字节")
        else:
            # 下载图片
            logger.info(f"从URL下载图像: {temp_image_url}")
            with httpx.Client(timeout=60.0) as client:
                resp = client.get(temp_image_url)
                resp.raise_for_status()
                image_data = resp.content
            logger.info(f"图像下载成功，大小: {len(image_data)} 字节")
        
        # 上传图片
        us3_client.upload_file_stream(image_data, put_key=filename, content_type="image/png")
        us3_url = us3_client.get_file_url(filename)
        
        scene.image_url = us3_url
        scene.status = "completed"

        # 保存图片生成历史到 scene.status_detail
        try:
            # 确保 status_detail 是字典
            if scene.status_detail is None:
                scene.status_detail = {}
            
            # 获取现有历史记录
            image_history = scene.status_detail.get('image_historys', [])
            
            # 添加新的历史记录（只保留图片链接和提示词）
            new_image_record = {
                "image_url": us3_url,
                "image_prompt": image_prompt,
                "generated_at": datetime.now().isoformat(),
            }
            
            image_history.append(new_image_record)
            scene.status_detail['image_historys'] = image_history
            
            # 显式标记 status_detail 字段已修改（SQLAlchemy JSONB 需要）
            flag_modified(scene, "status_detail")
            
            db.commit()
            db.refresh(scene)
            logger.info(f"场景 {scene_id} 图片生成历史保存成功，历史记录数: {len(image_history)}")
        except Exception as e:
            logger.error(f"保存场景 {scene_id} 图片生成历史失败: {str(e)}")
            # 历史保存失败不影响主流程

        # 扣除积分（场景图生成使用文生图模型）
        creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
        if creation:
            user_id = creation.owner_id
            try:
                deduct_points_for_image(
                    db=db,
                    user_id=user_id,
                    image_count=1,
                    model_name=ai_client.text_to_image_model or settings.IMAGE_MODEL_TEXT_TO_IMAGE or "black-forest-labs/flux-kontext-pro/multi",
                    reference_image_count=0,  # 文生图，无参考图
                    image_size="2K",
                    creation_id=creation_id,
                    novel_id=creation.novel_id,
                    description=f"生成场景图片（{scene.title}）",
                    scene_id=scene_id  # 用于幂等性检查，防止重试重复扣费
                )
                logger.info(f"场景 {scene_id} 图片生成积分扣除成功")
            except Exception as e:
                logger.opt(exception=True).error("场景图片生成积分扣除失败: {}", str(e))
                # 积分扣除失败不影响图片生成流程，只记录错误

        # 如果是单个任务（不是 batch 触发的），清除 current_task_id
        # 我们可以通过 check current_task_id 是否等于当前任务 ID 来判断
        if creation and str(creation.current_task_id) == str(self.request.id):
            creation.current_task_id = None

        db.commit()

        return {
            "status": "success",
            "scene_id": scene_id,
            "image_url": us3_url
        }

    except Exception as e:
        logger.error(f"Single Scene Image Generation Failed: {str(e)}")
        # 尝试更新状态为 failed
        try:
            scene = db.query(Scene).filter(Scene.scene_id == scene_id).first()
            if scene:
                scene.status = "failed"
                
                # 清除 current_task_id
                creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
                if creation and str(creation.current_task_id) == str(self.request.id):
                    creation.current_task_id = None
                
                db.commit()
        except:
            pass
        raise e
    finally:
        db.close()
