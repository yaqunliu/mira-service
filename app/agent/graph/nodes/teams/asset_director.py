"""
资产总监 Node - Asset Director

负责角色和场景图片的生成管理。
通过 LLM 生成图片提示词，创建 Celery 任务异步生成图片。
"""

from typing import Dict, Any, List
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.core.logger import logger
from app.core.config import settings
import json
import re


class AssetDirectorNode:
    """
    资产总监 Node
    
    职责：
    1. 查询待生成图片的角色和场景
    2. 通过 LLM 生成图片提示词
    3. 创建 Celery 任务异步生成图片
    """
    
    PROMPT_TEMPLATE = """你是专业的AI绘画提示词专家。根据以下{subject_type}描述，生成一个高质量的英文图片提示词。

## 描述
{description}

## 要求
1. 输出英文提示词，风格为日本动漫风格
2. 提示词应详细描述外观特征
3. 只输出提示词，不要其他内容

## 示例格式
1girl, long black hair, brown eyes, school uniform, standing, anime style, high quality"""
    
    def __init__(self):
        """初始化 LLM"""
        self.llm = ChatOpenAI(
            model="Qwen/Qwen-Plus",  # 使用更稳定的模型
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.5,
            timeout=30,  # 30秒超时
            max_retries=2,
        )
    
    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行资产生成
        
        Args:
            state: 当前状态
            
        Returns:
            执行结果
        """
        creation_uuid = state.get("creation_uuid")
        
        try:
            # 使用 Tool 查询待生成图片的资产
            from app.agent.tools.db_tools import query_pending_assets
            
            result = await query_pending_assets.ainvoke({"creation_uuid": creation_uuid})
            
            if not result.get("success"):
                return {
                    "response_text": f"查询资产失败：{result.get('error')}",
                    "production_stage": ProductionStage.SCRIPT_ANALYZED,
                    "errors": [{"message": result.get("error")}],
                }
            
            pending_characters = result.get("pending_characters", [])
            pending_scenes = result.get("pending_scenes", [])
            
            # 构建资产列表并生成提示词
            assets_to_generate = []
            
            # 生成角色提示词
            for char in pending_characters:
                prompt = await self._generate_prompt("角色", char["appearance"] or char["name"])
                assets_to_generate.append({
                    "type": "character",
                    "id": char["id"],
                    "name": char["name"],
                    "prompt": prompt,
                })
                logger.info(f"[AssetDirector] 准备角色图片任务: {char['name']}")
            
            # 生成场景提示词
            for scene in pending_scenes:
                prompt = await self._generate_prompt("场景", scene["description"] or scene["title"])
                assets_to_generate.append({
                    "type": "scene",
                    "id": scene["id"],
                    "name": scene["title"],
                    "prompt": prompt,
                })
                logger.info(f"[AssetDirector] 准备场景图片任务: {scene['title']}")
            
            # 使用 Tool 创建生成任务
            from app.agent.tools.db_tools import create_asset_generation_tasks
            
            task_result = await create_asset_generation_tasks.ainvoke({
                "creation_uuid": creation_uuid,
                "assets": assets_to_generate,
            })
            
            if not task_result.get("success"):
                return {
                    "response_text": f"创建图片生成任务失败：{task_result.get('error')}",
                    "production_stage": ProductionStage.SCRIPT_ANALYZED,
                    "errors": [{"message": task_result.get("error")}],
                }
            
            task_ids = task_result.get("task_ids", [])
            
            # 更新进度
            production_progress = dict(state.get("production_progress", {}))
            production_progress["asset_generation"] = {
                "status": "processing",
                "task_ids": task_ids,
                "total": task_result.get("total", 0),
                "characters": task_result.get("characters_count", 0),
                "scenes": task_result.get("scenes_count", 0),
            }
            
            # 如果没有待生成的资产，直接返回完成
            if not task_ids:
                production_progress["asset_generation"]["status"] = "completed"
                return {
                    "response_text": "所有角色和场景图片都已生成完成！请在看板上查看并确认。",
                    "production_stage": ProductionStage.ASSETS_READY,
                    "production_progress": production_progress,
                    "pending_approval": True,
                    "checkpoint_data": {
                        "checkpoint_type": "asset_finalization",
                        "data": {"characters_generated": 0, "scenes_generated": 0},
                        "message": "请确认角色和场景形象",
                    },
                    "board_actions": [
                        {"type": "switch_view", "target": "characters"},
                    ],
                }
            
            # 有任务在生成中，开始等待任务完成
            logger.info(f"[AssetDirector] 开始等待 {len(task_ids)} 个图片生成任务完成...")
            
            # 异步轮询等待任务完成
            import asyncio
            from app.agent.tools.db_tools import query_characters, query_scenes
            
            max_wait_time = 300  # 最长等待 5 分钟
            poll_interval = 5   # 每 5 秒检查一次
            elapsed = 0
            chars_with_images = 0
            scenes_with_images = 0
            total_chars = 0
            total_scenes = 0
            
            while elapsed < max_wait_time:
                try:
                    logger.debug(f"[AssetDirector] 进入 sleep，elapsed={elapsed}s")
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
                    logger.debug(f"[AssetDirector] sleep 完成，elapsed={elapsed}s")
                except asyncio.CancelledError as e:
                    logger.warning(f"[AssetDirector] asyncio.sleep 被取消: {e}, elapsed={elapsed}s")
                    raise
                except Exception as e:
                    logger.error(f"[AssetDirector] asyncio.sleep 异常: {type(e).__name__}: {e}")
                    raise
                
                # 查询当前角色和场景状态
                chars_result = await query_characters.ainvoke({"creation_uuid": creation_uuid})
                scenes_result = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
                
                characters = chars_result.get("characters", [])
                scenes = scenes_result.get("scenes", [])
                
                # 检查是否所有资产都有图片
                chars_with_images = sum(1 for c in characters if c.get("image_url"))
                scenes_with_images = sum(1 for s in scenes if s.get("image_url"))
                
                total_chars = len(characters)
                total_scenes = len(scenes)
                
                logger.info(f"[AssetDirector] 轮询检查 (已等待 {elapsed}s): 角色 {chars_with_images}/{total_chars}, 场景 {scenes_with_images}/{total_scenes}")
                
                # 更新进度信息
                production_progress["asset_generation"]["completed_characters"] = chars_with_images
                production_progress["asset_generation"]["completed_scenes"] = scenes_with_images
                
                # 检查是否全部完成
                if chars_with_images >= total_chars and scenes_with_images >= total_scenes:
                    logger.info(f"[AssetDirector] 所有图片生成完成！共耗时 {elapsed}s")
                    production_progress["asset_generation"]["status"] = "completed"
                    
                    return {
                        "response_text": f"""✅ **图片生成完成！**

🎨 **生成结果**：
- 角色图片：{chars_with_images} 个已完成
- 场景图片：{scenes_with_images} 个已完成

总耗时：{elapsed} 秒

请在看板上查看并确认角色和场景形象。""",
                        "production_stage": ProductionStage.ASSETS_READY,
                        "production_progress": production_progress,
                        "pending_approval": True,
                        "checkpoint_data": {
                            "checkpoint_type": "asset_finalization",
                            "data": {"characters_generated": chars_with_images, "scenes_generated": scenes_with_images},
                            "message": "请确认角色和场景形象",
                        },
                        "board_actions": [
                            {"type": "switch_view", "target": "characters"},
                            {"type": "refresh"},
                        ],
                    }
            
            # 超时未完成
            logger.warning(f"[AssetDirector] 等待超时 ({max_wait_time}s)，部分任务可能未完成")
            return {
                "response_text": f"""⏳ **图片生成仍在进行中**

已等待 {max_wait_time} 秒，部分任务可能仍在处理：
- 角色图片：{chars_with_images}/{total_chars} 个已完成
- 场景图片：{scenes_with_images}/{total_scenes} 个已完成

请稍后发送"查看进度"查看最新状态。""",
                "production_stage": ProductionStage.ASSETS_GENERATING,
                "production_progress": production_progress,
                "pending_approval": False,
                "board_actions": [
                    {"type": "switch_view", "target": "characters"},
                    {"type": "refresh"},
                ],
            }
            
        except Exception as e:
            logger.error(f"[AssetDirector] 执行失败: {e}")
            return {
                "response_text": f"资产生成过程中出现错误：{str(e)}",
                "production_stage": ProductionStage.SCRIPT_ANALYZED,
                "errors": [{"message": str(e)}],
            }
    
    async def _generate_prompt(self, subject_type: str, description: str) -> str:
        """使用 LLM 生成图片提示词"""
        try:
            prompt = self.PROMPT_TEMPLATE.format(
                subject_type=subject_type,
                description=description
            )
            response = await self.llm.ainvoke(prompt)
            return response.content.strip()
        except Exception as e:
            logger.warning(f"[AssetDirector] 生成提示词失败: {e}，使用原始描述")
            return description


# 便捷函数
async def generate_assets(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = AssetDirectorNode()
    return await node.run(state)
