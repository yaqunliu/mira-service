from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from sqlalchemy.orm import Session
from typing import List
from app.models.character import Character
from app.models.creation import Creation
from app.schemas.creation import CreationStatus
from app.core.exceptions import NotFoundError, BaseServiceException
from app.utils.task_types import TaskType
from app.utils.ai_client import AIClient
from app.core.logger import logger
from app.utils.file_utils import read_prompt_file
from app.utils.us3 import US3Client
from app.utils.points_deduction import deduct_points_for_image
from app.core.config import settings
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
import uuid
import tempfile
import os


def _generate_single_character_image(character_id: int, visual_style: str) -> dict:
    """
    生成单个角色的图片（线程安全函数）
    
    Args:
        character_id: 角色ID
        visual_style: 视觉风格
        
    Returns:
        包含角色ID和处理结果的字典
        
    Raises:
        NotFoundError: 角色不存在
        Exception: 生图失败
    """
    db: Session = SessionLocal()
    try:
        character = (
            db.query(Character)
            .filter(Character.character_id == character_id)
            .first()
        )
        if not character:
            raise NotFoundError(detail=f"角色不存在: character_id={character_id}")
        
        # 生成提示词
        system_prompt = read_prompt_file("character.md")
        image_prompt = (
            f"{system_prompt}\n"
            # f"视觉风格：{visual_style}，"
            f"基本信息：{character.basic_info}，"
            f"外貌特征：{character.appearance}，"
            f"身材特征：{character.body}，"
            f"发型：{character.hair}，"
            f"服装：{character.clothing}，"
            f"特征标签：{character.tags}。"
        )
        # logger.info(f"{character.name}生成图片提示词: {image_prompt}")
        
        # 调用生图API
        temp_image_url = AIClient().generate_image_by_prompt(
            prompt=image_prompt,
        )
        
        # 从临时URL下载图像并上传到US3进行持久化
        temp_file_path = None
        try:
            logger.info(f"从URL下载图像: {temp_image_url}")
            # 下载图像
            with httpx.Client(timeout=30.0) as client:
                response = client.get(temp_image_url)
                response.raise_for_status()
                image_data = response.content
            logger.info(f"图像下载成功，大小: {len(image_data)} 字节")
            
            # 将图像数据保存到临时文件（US3 SDK 需要文件路径）
            image_extension = ".png"  # 默认使用png，可以根据实际返回的格式调整
            temp_fd, temp_file_path = tempfile.mkstemp(suffix=image_extension)
            try:
                with os.fdopen(temp_fd, 'wb') as tmp_file:
                    tmp_file.write(image_data)
                logger.info(f"图像已保存到临时文件: {temp_file_path}")
            except Exception as e:
                os.close(temp_fd)  # 如果写入失败，关闭文件描述符
                raise
            
            # 上传到US3
            # 生成US3存储路径: characters/{character_id}/image_{uuid}.png
            image_uuid = str(uuid.uuid4())
            put_key = f"characters/{character_id}/image_{image_uuid}{image_extension}"
            
            us3_client = US3Client()
            upload_result = us3_client.upload_file(
                local_file=temp_file_path,
                bucket=None,  # 使用默认bucket
                put_key=put_key
            )
            
            if not upload_result['success']:
                error_msg = f"图像上传US3失败: {upload_result.get('message')}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            # 生成US3持久化URL
            persistent_image_url = us3_client.get_file_url(put_key)
            logger.info(f"图像上传US3成功，持久化URL: {persistent_image_url}")
            
            # 使用US3持久化URL
            image_url = persistent_image_url
            
        except Exception as e:
            # 如果US3上传失败，记录错误但继续使用临时URL（降级处理）
            error_msg = f"图像上传US3失败，使用临时URL: {str(e)}"
            logger.warning(error_msg, exc_info=True)
            image_url = temp_image_url  # 降级使用临时URL
        finally:
            # 清理临时文件
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    logger.debug(f"已清理临时文件: {temp_file_path}")
                except Exception as e:
                    logger.warning(f"删除临时文件失败: {str(e)}")
        
        # 更新角色信息
        character.image_url = image_url
        character.image_prompt = image_prompt
        # character.image_base64 = image_base64

        # 获取用户ID和相关信息用于积分扣除
        user_id = None
        creation_id = character.creation_id
        novel_id = character.novel_id
        
        if creation_id:
            creation = db.query(Creation).filter(Creation.creation_id == creation_id).first()
            if creation:
                creation.status = CreationStatus.CHARACTER_GENERATED
                user_id = creation.owner_id
                novel_id = creation.novel_id or novel_id
        elif novel_id:
            # 如果没有 creation_id，通过 novel_id 获取用户ID
            from app.models.novel import Novel
            novel = db.query(Novel).filter(Novel.novel_id == novel_id).first()
            if novel:
                user_id = novel.owner_id
        
        # 扣除积分（按实际成本，带幂等性检查）
        # 角色生成使用文生图模型
        if user_id:
            try:
                deduct_points_for_image(
                    db=db,
                    user_id=user_id,
                    image_count=1,
                    model_name=settings.IMAGE_MODEL_TEXT_TO_IMAGE or settings.IMAGE_MODEL_NAME or "black-forest-labs/flux-kontext-pro/multi",
                    creation_id=creation_id,
                    novel_id=novel_id,
                    description=f"生成角色图片（{character.name}）",
                    character_id=character_id  # 用于幂等性检查，防止重试重复扣费
                )
                logger.info(f"角色 {character_id} 图片生成积分扣除成功")
            except Exception as e:
                logger.error(f"角色图片生成积分扣除失败: {str(e)}", exc_info=True)
                # 积分扣除失败不影响图片生成流程，只记录错误
        else:
            logger.warning(f"角色 {character_id} 无法获取用户ID，跳过积分扣除（creation_id={creation_id}, novel_id={novel_id}）")

        db.commit()
        db.refresh(character)
        if creation_id:
            db.refresh(creation)
        
        logger.info(f"角色 {character.name}(ID: {character_id}) 图片生成成功")
        return {
            "character_id": character_id,
            "character_name": character.name,
            "success": True,
            "image_url": image_url
        }
    except Exception as e:
        logger.error(f"角色 {character_id} 图片生成失败: {str(e)}", exc_info=True)
        db.rollback()
        return {
            "character_id": character_id,
            "success": False,
            "error": str(e)
        }
    finally:
        db.close()


@celery_app.task(bind=True, name="generate_character_image_task")
def generate_character_image_task(self, character_ids: List[int], visual_style: str):
    """
    并发生成多个角色的图片
    
    Args:
        character_ids: 角色ID列表
        visual_style: 视觉风格
        
    Returns:
        包含所有角色处理结果的字典
    """
    if not character_ids:
        logger.warning("角色ID列表为空")
        return {
            "success": False,
            "message": "角色ID列表为空",
            "results": []
        }
    
    total_count = len(character_ids)
    logger.info(f"开始并发生成 {total_count} 个角色的图片: {character_ids}")
    
    # 更新任务状态
    self.update_state(
        state="PROGRESS",
        meta={
            "task_type": TaskType.CHARACTER_IMAGE_GENERATION,
            "character_ids": character_ids,
            "total": total_count,
            "completed": 0,
            "failed": 0,
        },
    )
    
    results = []
    success_count = 0
    failed_count = 0
    
    try:
        # 使用线程池并发执行（最多5个并发）
        max_workers = min(5, total_count)  # 限制最大并发数，避免过多请求
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_character_id = {
                executor.submit(_generate_single_character_image, cid, visual_style): cid
                for cid in character_ids
            }
            
            # 收集结果
            for future in as_completed(future_to_character_id):
                character_id = future_to_character_id[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result["success"]:
                        success_count += 1
                        logger.info(f"角色 {character_id} 图片生成成功")
                    else:
                        failed_count += 1
                        logger.warning(f"角色 {character_id} 图片生成失败: {result.get('error')}")
                    
                    # 更新任务进度
                    self.update_state(
                        state="PROGRESS",
                        meta={
                            "task_type": TaskType.CHARACTER_IMAGE_GENERATION,
                            "character_ids": character_ids,
                            "total": total_count,
                            "completed": success_count + failed_count,
                            "success": success_count,
                            "failed": failed_count,
                        },
                    )
                except Exception as e:
                    failed_count += 1
                    error_msg = f"角色 {character_id} 处理异常: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    results.append({
                        "character_id": character_id,
                        "success": False,
                        "error": error_msg
                    })
        
        # 任务完成
        logger.info(
            f"角色图片生成任务完成: 总数={total_count}, "
            f"成功={success_count}, 失败={failed_count}"
        )
        
        return {
            "success": failed_count == 0,  # 全部成功才算成功
            "total": total_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }
        
    except Exception as e:
        error_msg = f"角色图片生成任务失败: {str(e)}"
        logger.error(error_msg, exc_info=True)
        self.update_state(
            state="FAILURE",
            meta={
                "task_type": TaskType.CHARACTER_IMAGE_GENERATION,
                "character_ids": character_ids,
                "error": error_msg,
            },
        )
        raise BaseServiceException(message=error_msg)
