"""
分镜导演节点 - StoryboardDirectorNode

两步 LLM 流程：
1. LLM 生成分镜脚本（描述、旁白、时长）→ save_shots Tool 保存
2. LLM 生成图片提示词（首帧/尾帧）→ save_shot_prompts Tool 保存
3. generate_shot_images Tool 触发图片生成任务
"""

import json
from typing import Any, Dict, List

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.core.config import settings
from app.core.logger import logger


class StoryboardDirectorNode:
    """
    分镜导演节点
    
    职责:
    1. LLM 生成分镜脚本（调用 save_shots Tool 保存）
    2. LLM 生成图片提示词（调用 save_shot_prompts Tool 保存）
    3. 触发分镜图片生成任务（调用 generate_shot_images Tool）
    """
    
    # 第一步：生成分镜脚本
    SCRIPT_PROMPT = """你是一位专业的分镜导演，负责将剧本拆解为详细的分镜脚本。

## 输出格式
返回 JSON 数组，每个分镜包含：
- scene_name: 所属场景名称（必须与已有场景标题完全一致）
- title: 分镜标题
- description: 画面描述（详细描述镜头内容、人物动作、表情等）
- characters: 出场角色名称数组（必须与已有角色名称完全一致，如 ["林晚", "李明"]）
- narration: 旁白或对话内容（JSON数组格式：[{"角色": "角色名", "内容": "对话内容"}]）
- duration: 预估时长（秒，3-8秒）

## 要求
1. 分镜数量控制在 15-30 个
2. 每个分镜时长 3-8 秒
3. 画面描述要详细具体，便于后续生成图片
4. 保持剧情连贯性和节奏感
5. **characters 字段必须填写本分镜中出现的所有角色名称**

## 输出示例
```json
[
    {
        "scene_name": "咖啡厅",
        "title": "初次相遇",
        "description": "女主角坐在靠窗的位置，阳光透过玻璃洒在她的脸上，她正在看书。",
        "characters": ["林晚"],
        "narration": [{"角色": "旁白", "内容": "那是一个平凡的午后"}],
        "duration": 5
    }
]
```

只输出 JSON，不要其他内容。"""

    # 第二步：生成图片提示词 - 专业版（参考 shot_image_v4.md）
    PROMPT_GENERATION_PROMPT = """你是一位世界级电影导演兼专业布景师，负责为分镜生成首帧和尾帧的静态图片提示词。

## 视觉风格
{visual_style}

## 角色档案
{character_profiles}

## 场景环境
{scene_environment}

## 核心创作原则

### 1. 情绪分析（必须）
在生成每个分镜的提示词前，先分析角色的情绪状态：
- 表面情绪与内心情绪
- 情绪转变（首帧 → 尾帧）
- 通过面部表情、眼神、肢体语言传达

### 2. 景别选择（灵活）
根据故事需要选择最合适的景别：
- **远景/全景**：建立空间感、交代环境
- **中景**：展示肢体动作、多人互动
- **近景/特写**：强调面部表情、传达情绪

### 3. 首尾帧区分
- **首帧**：分镜开始时的画面状态（动作起点 + 起始情绪）
- **尾帧**：分镜结束时的画面状态，可以是：
  - 眼睛特写（情感高潮）
  - 手部特写（动作/情绪细节）
  - 物品特写（象征意义）
  - 脚步特写（奔跑/离别）

### 4. 禁止事项
- ❌ 禁止镜头运动描述（推镜、拉镜、平移）
- ❌ 禁止动态过程（"从...到..."、"逐渐..."）
- ✅ 只描述固定的瞬间画面

## 分镜列表
{shots_description}

## 输出格式
返回 JSON 数组，每项包含：
```json
[
    {{
        "shot_number": 1,
        "emotion_analysis": {{
            "character": "角色名",
            "start_emotion": "首帧情绪",
            "end_emotion": "尾帧情绪"
        }},
        "image_prompt": "首帧提示词（英文，包含风格、景别、角色外貌、表情、服装、场景、光影）",
        "end_frame_prompt": "尾帧提示词（英文，可以是特写或不同景别，体现情绪/动作变化）"
    }}
]
```

## 提示词模板
首帧：`{visual_style}, [景别], [视角]视角, 16:9宽屏构图. [场景描述]. [角色名]([外貌特征], [服装], [表情], [眼神], [肢体语言]), 位于画面[位置]. [光影氛围], high quality, 8K detail.`

尾帧（特写模式）：`{visual_style}, extreme close-up, 16:9构图. [聚焦部位]的特写: [细节描述], [情绪体现]. [光影], high quality, 8K detail.`

只输出 JSON，不要其他内容。"""
    
    def __init__(self):
        """初始化 LLM"""
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_DEFAULT,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.5,
            timeout=90,
            max_retries=2,
        )
    
    async def _check_progress(self, creation_uuid: str, query_shots) -> Dict[str, Any]:
        """
        检查当前分镜进度，确定从哪个步骤继续
        
        Returns:
            {
                "step": 0-5,  # 当前完成的步骤
                "total_shots": int,
                "with_prompts": int,
                "with_images": int,
            }
        """
        result = await query_shots.ainvoke({
            "creation_uuid": creation_uuid,
            "include_details": True,
        })
        
        # 直接使用 query_shots 返回的汇总数据
        total = result.get("total", 0)
        with_images = result.get("with_image", 0)
        
        if total == 0:
            return {"step": 0, "total_shots": 0, "with_prompts": 0, "with_images": 0}
        
        # 统计有提示词的分镜数
        shots = result.get("shots", [])
        with_prompts = sum(1 for s in shots if s.get("image_prompt"))
        
        # 确定当前步骤
        if with_images >= total:
            step = 5  # 全部完成
        elif with_prompts >= total:
            step = 3  # 有提示词，可直接生成图片
        else:
            step = 1  # 有分镜，但需要生成提示词
        
        logger.info(f"[StoryboardDirector] 进度检查: total={total}, with_prompts={with_prompts}, with_images={with_images}, step={step}")
        
        return {
            "step": step,
            "total_shots": total,
            "with_prompts": with_prompts,
            "with_images": with_images,
        }
    
    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行分镜创建（支持断点续传）
        
        进度检查逻辑：
        1. 如果已有分镜且有图片 → 直接返回成功
        2. 如果已有分镜且有提示词 → 从 Step 5 继续（生成图片）
        3. 如果已有分镜但无提示词 → 从 Step 3 继续（生成提示词）
        4. 如果无分镜 → 从 Step 1 开始
        """
        creation_uuid = state.get("creation_uuid")
        script_text = state.get("script_text")
        
        if not script_text:
            return {
                "response_text": "请先上传剧本内容。",
                "production_stage": ProductionStage.INIT,
                "needs_input": True,
            }
        
        try:
            from app.agent.tools.db_tools import (
                query_scene_titles, save_shots, save_shot_prompts, query_shots
            )
            from app.agent.tools.agent_generation_tools import generate_shot_images
            
            # ========== 检查当前进度 ==========
            progress = await self._check_progress(creation_uuid, query_shots)
            logger.info(f"[StoryboardDirector] 进度检查: {progress}")
            
            shot_count = progress["total_shots"]
            shots_data = None  # 仅在需要生成时使用
            
            # ========== Step 1 & 2: 生成并保存分镜脚本 ==========
            if progress["step"] < 1:
                logger.info("[StoryboardDirector] Step 1: LLM 生成分镜脚本...")
                
                scene_result = await query_scene_titles.ainvoke({"creation_uuid": creation_uuid})
                scene_titles = scene_result.get("scene_titles", []) if scene_result.get("success") else []
                
                script_prompt = f"""根据以下剧本生成分镜脚本：

## 剧本内容
{script_text[:6000]}

## 可用场景
{', '.join(scene_titles) if scene_titles else '无（请自行创建场景名）'}

请生成分镜脚本。"""
                
                response = await self.llm.ainvoke([
                    SystemMessage(content=self.SCRIPT_PROMPT),
                    HumanMessage(content=script_prompt)
                ])
                
                shots_data = self._parse_json_response(response.content)
                if not shots_data:
                    return {
                        "response_text": "分镜脚本生成失败，请重试。",
                        "production_stage": ProductionStage.ASSETS_READY,
                        "errors": [{"message": "分镜脚本 JSON 解析失败"}],
                    }
                
                logger.info(f"[StoryboardDirector] LLM 生成 {len(shots_data)} 个分镜")
                
                # Step 2: 保存分镜
                logger.info("[StoryboardDirector] Step 2: 保存分镜脚本到数据库...")
                
                save_result = await save_shots.ainvoke({
                    "creation_uuid": creation_uuid,
                    "shots": shots_data,
                })
                
                if not save_result.get("success"):
                    return {
                        "response_text": f"保存分镜失败：{save_result.get('error')}",
                        "production_stage": ProductionStage.ASSETS_READY,
                        "errors": [{"message": save_result.get("error")}],
                    }
                
                shot_count = save_result.get("saved_count", 0)
                logger.info(f"[StoryboardDirector] Tool 保存 {shot_count} 个分镜")
            else:
                logger.info(f"[StoryboardDirector] ⏭️ 跳过 Step 1-2: 已有 {shot_count} 个分镜")
            
            # ========== Step 3 & 4: 生成并保存图片提示词 ==========
            if progress["step"] < 3:
                logger.info("[StoryboardDirector] Step 3: LLM 生成图片提示词（专业版）...")
                
                # 需要从 DB 获取分镜描述
                if not shots_data:
                    shots_result = await query_shots.ainvoke({
                        "creation_uuid": creation_uuid,
                        "include_details": True,
                    })
                    existing_shots = shots_result.get("shots", [])
                    shots_desc = "\n".join([
                        f"{i+1}. 【分镜{i+1}】{s.get('description', s.get('narration', ''))}"
                        for i, s in enumerate(existing_shots)
                    ])
                    shot_count = len(existing_shots)
                else:
                    shots_desc = "\n".join([
                        f"{i+1}. 【{s.get('title', f'分镜{i+1}')}】{s.get('description', '')}"
                        for i, s in enumerate(shots_data)
                    ])
                
                # 获取视觉风格
                visual_style = "日本动漫风格"  # 默认
                if state.get("creation_extra_data"):
                    extra_data = state.get("creation_extra_data", {})
                    visual_style = extra_data.get("visual_style", visual_style)
                
                # 获取角色档案
                character_profiles = "未指定角色"
                try:
                    from app.agent.tools.db_tools import query_characters
                    chars_result = await query_characters.ainvoke({"creation_uuid": creation_uuid})
                    if chars_result.get("success"):
                        characters = chars_result.get("characters", [])
                        if characters:
                            profiles = []
                            for char in characters:
                                profile = f"- {char.get('name', '未知')}"
                                if char.get("appearance"):
                                    profile += f": {char['appearance']}"
                                if char.get("costume"):
                                    profile += f"，服装: {char['costume']}"
                                profiles.append(profile)
                            character_profiles = "\n".join(profiles)
                except Exception as e:
                    logger.warning(f"[StoryboardDirector] 获取角色档案失败: {e}")
                
                # 获取场景环境
                scene_environment = "未指定场景"
                try:
                    from app.agent.tools.db_tools import query_scenes
                    scenes_result = await query_scenes.ainvoke({"creation_uuid": creation_uuid})
                    if scenes_result.get("success"):
                        scenes = scenes_result.get("scenes", [])
                        if scenes:
                            scene_descs = []
                            for scene in scenes:
                                desc = f"- {scene.get('title', '未知场景')}"
                                if scene.get("description"):
                                    desc += f": {scene['description']}"
                                scene_descs.append(desc)
                            scene_environment = "\n".join(scene_descs)
                except Exception as e:
                    logger.warning(f"[StoryboardDirector] 获取场景信息失败: {e}")
                
                # 格式化专业模板
                formatted_prompt = self.PROMPT_GENERATION_PROMPT.format(
                    visual_style=visual_style,
                    character_profiles=character_profiles,
                    scene_environment=scene_environment,
                    shots_description=shots_desc,
                )
                
                prompt_request = f"""为以下 {shot_count} 个分镜生成首帧和尾帧图片提示词，请严格按照上述专业要求生成。"""
                
                prompt_response = await self.llm.ainvoke([
                    SystemMessage(content=formatted_prompt),
                    HumanMessage(content=prompt_request)
                ])
                
                prompts_data = self._parse_json_response(prompt_response.content)
                if not prompts_data:
                    logger.warning("[StoryboardDirector] 图片提示词生成失败")
                else:
                    logger.info(f"[StoryboardDirector] LLM 生成 {len(prompts_data)} 个专业提示词")
                    
                    # Step 4: 保存提示词
                    logger.info("[StoryboardDirector] Step 4: 保存图片提示词...")
                    
                    prompts_result = await save_shot_prompts.ainvoke({
                        "creation_uuid": creation_uuid,
                        "prompts": prompts_data,
                    })
                    
                    if prompts_result.get("success"):
                        logger.info(f"[StoryboardDirector] Tool 更新 {prompts_result.get('updated_count')} 个分镜提示词")
                    else:
                        logger.warning(f"[StoryboardDirector] 保存提示词失败: {prompts_result.get('error')}")
            else:
                logger.info(f"[StoryboardDirector] ⏭️ 跳过 Step 3-4: 已有 {progress['with_prompts']} 个提示词")
            
            # ========== Step 5: 触发图片生成 ==========
            if progress["step"] < 5:
                logger.info("[StoryboardDirector] Step 5: 触发分镜图片生成...")
                
                gen_result = await generate_shot_images.ainvoke({
                    "creation_uuid": creation_uuid,
                    "force_regenerate": False,
                })
                
                if not gen_result.get("success"):
                    if gen_result.get("task_id") is None and "无需生成" in str(gen_result.get("message", "")):
                        # 所有分镜已有图片
                        logger.info("[StoryboardDirector] 所有分镜已有图片，无需生成")
                    else:
                        return {
                            "response_text": f"分镜图生成启动失败：{gen_result.get('error')}",
                            "production_stage": ProductionStage.STORYBOARD_GENERATING,
                            "errors": [{"message": gen_result.get("error")}],
                        }
                
                task_id = gen_result.get("task_id")
                
                if task_id:
                    task_id = gen_result.get("task_id")
                    group_id = gen_result.get("group_id")
                    shot_task_ids = gen_result.get("shot_task_ids", {})
                    logger.info(f"[StoryboardDirector] 触发分镜图生成任务: task_id={task_id}, group_id={group_id}, shots={len(shot_task_ids)}")
            else:
                logger.info(f"[StoryboardDirector] ⏭️ 跳过 Step 5: 已有 {progress['with_images']} 个图片")
                task_id = None
                group_id = None
                shot_task_ids = {}
                
                # 所有步骤已完成，直接返回成功
                if progress["with_images"] >= progress["total_shots"]:
                    logger.info(f"[StoryboardDirector] 所有分镜已有图片，直接返回完成状态")
                    return {
                        "response_text": f"""✅ **分镜创作已完成！**

📋 **分镜数量**: {progress['total_shots']} 个
🖼️ **分镜图片**: 全部已生成

所有分镜图片已生成完成，是否开始下一阶段（生成视频）？

请在分镜看板上查看结果，确认后回复"继续"开始视频生成。""",
                        "production_stage": ProductionStage.STORYBOARD_READY,
                        "pending_approval": True,
                        "board_actions": [
                            {"type": "switch_view", "target": "storyboards"},
                            {"type": "refresh"},
                        ],
                    }
            
            # 更新进度
            production_progress = dict(state.get("production_progress", {}))
            production_progress["storyboard_creation"] = {
                "status": "generating_images",
                "total": shot_count,
                "completed": progress["with_images"],
                "task_id": task_id,
                "group_id": group_id,
            }
            
            # ========== Step 6: 使用 Task Group 状态轮询 ==========
            import asyncio
            from app.agent.tools.agent_generation_tools import check_task_group_status
            
            max_wait_time = 600
            poll_interval = 5
            elapsed = 0
            
            while elapsed < max_wait_time and shot_task_ids:
                try:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval
                except asyncio.CancelledError:
                    logger.warning(f"[StoryboardDirector] 轮询被取消")
                    raise
                
                # 检查任务组状态
                group_status = await check_task_group_status.ainvoke({
                    "group_id": group_id or "",
                    "shot_task_ids": shot_task_ids,
                })
                
                completed = group_status.get("completed", 0)
                failed = group_status.get("failed", 0)
                pending = group_status.get("pending", 0)
                total = group_status.get("total", 0)
                all_done = group_status.get("all_done", False)
                
                logger.info(f"[StoryboardDirector] 轮询 ({elapsed}s): 完成={completed}, 失败={failed}, 待处理={pending}")
                
                production_progress["storyboard_creation"]["completed"] = completed
                
                # 检查是否有失败
                if failed > 0 and all_done:
                    failed_shots = group_status.get("failed_shots", [])
                    error_msg = f"有 {failed} 个分镜图片生成失败"
                    if failed_shots:
                        error_details = ", ".join([f"shot_id={s['shot_id']}: {s.get('error', 'Unknown')[:50]}" for s in failed_shots[:3]])
                        error_msg += f": {error_details}"
                    
                    logger.error(f"[StoryboardDirector] {error_msg}")
                    
                    # 部分成功的情况：返回部分完成状态
                    if completed > 0:
                        return {
                            "response_text": f"""⚠️ **分镜图片生成部分完成**

📋 **分镜数量**: {total} 个
✅ **成功**: {completed} 个
❌ **失败**: {failed} 个

部分分镜图片生成失败，您可以在看板中查看并重试失败的分镜。""",
                            "production_stage": ProductionStage.STORYBOARD_GENERATING,
                            "production_progress": production_progress,
                            "errors": [{"message": error_msg}],
                            "board_actions": [
                                {"type": "switch_view", "target": "storyboards"},
                                {"type": "refresh"},
                            ],
                        }
                    else:
                        raise Exception(error_msg)
                
                # 全部完成
                if all_done and failed == 0:
                    logger.info(f"[StoryboardDirector] 所有分镜图生成完成！耗时 {elapsed}s")
                    
                    production_progress["storyboard_creation"]["status"] = "completed"
                    
                    return {
                        "response_text": f"""✅ **分镜创作完成！**

📋 **分镜数量**: {total} 个
🖼️ **首帧图片**: 全部生成完成
🖼️ **尾帧图片**: 全部生成完成

所有分镜图片（包括首帧和尾帧）已生成完成！

请在分镜看板上查看结果，确认后回复"继续"开始下一阶段（视频生成）。""",
                        "production_stage": ProductionStage.STORYBOARD_READY,
                        "production_progress": production_progress,
                        "pending_approval": True,
                        "board_actions": [
                            {"type": "switch_view", "target": "storyboards"},
                            {"type": "refresh"},
                        ],
                    }
            
            # 如果没有 shot_task_ids（使用旧的轮询方式 fallback）
            if not shot_task_ids:
                shots_result = await query_shots.ainvoke({"creation_uuid": creation_uuid})
                shots = shots_result.get("shots", [])
                shots_with_images = sum(1 for s in shots if s.get("image_url"))
                total_shots = len(shots)
                
                if total_shots > 0 and shots_with_images >= total_shots:
                    production_progress["storyboard_creation"]["status"] = "completed"
                    return {
                        "response_text": f"""✅ **分镜创作完成！**

📋 **分镜数量**: {total_shots} 个
🖼️ **分镜图片**: 全部生成完成

请在分镜看板上查看结果，确认后回复"继续"开始下一阶段（视频生成）。""",
                        "production_stage": ProductionStage.STORYBOARD_READY,
                        "production_progress": production_progress,
                        "pending_approval": True,
                        "board_actions": [
                            {"type": "switch_view", "target": "storyboards"},
                            {"type": "refresh"},
                        ],
                    }
            
            # 超时
            logger.warning(f"[StoryboardDirector] 等待超时 ({max_wait_time}s)")
            return {
                "response_text": f"""⏳ **分镜图生成仍在进行中**

📋 **分镜数量**: {shot_count} 个
🖼️ **已完成**: {production_progress['storyboard_creation'].get('completed', 0)} 个

部分图片仍在生成中，您可以稍后在看板上查看进度。
图片生成完成后，回复"继续"开始下一阶段。""",
                "production_stage": ProductionStage.STORYBOARD_GENERATING,
                "production_progress": production_progress,
                "pending_approval": False,
                "board_actions": [
                    {"type": "switch_view", "target": "storyboards"},
                    {"type": "refresh"},
                ],
            }
            
        except Exception as e:
            logger.error(f"[StoryboardDirector] 执行失败: {e}")
            return {
                "response_text": f"分镜创建过程中出现错误：{str(e)}",
                "production_stage": ProductionStage.ASSETS_READY,
                "errors": [{"message": str(e)}],
            }
    
    def _parse_json_response(self, content: str) -> List[Dict] | None:
        """解析 LLM 返回的 JSON，带有错误修复能力"""
        import re
        
        if not content:
            logger.error("[StoryboardDirector] LLM 返回内容为空")
            return None
        
        content = content.strip()
        
        # 从 markdown 代码块提取
        if "```" in content:
            pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
            matches = re.findall(pattern, content)
            if matches:
                content = matches[0].strip()
                logger.debug(f"[StoryboardDirector] 从代码块提取 JSON，长度: {len(content)}")
        
        # 查找 JSON 数组边界
        start_idx = content.find("[")
        end_idx = content.rfind("]")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            content = content[start_idx:end_idx + 1]
        
        # 尝试多种解析策略
        parse_attempts = [
            ("直接解析", lambda c: json.loads(c)),
            ("修复尾部逗号", lambda c: json.loads(re.sub(r',\s*([}\]])', r'\1', c))),
            ("修复未闭合括号", self._fix_json_brackets),
        ]
        
        for attempt_name, parse_func in parse_attempts:
            try:
                result = parse_func(content)
                if isinstance(result, list) and len(result) > 0:
                    logger.info(f"[StoryboardDirector] JSON 解析成功 ({attempt_name}): {len(result)} 项")
                    return result
            except json.JSONDecodeError as e:
                logger.debug(f"[StoryboardDirector] {attempt_name} 失败: {e}")
                continue
            except Exception as e:
                logger.debug(f"[StoryboardDirector] {attempt_name} 异常: {e}")
                continue
        
        # 最后尝试：逐个对象解析
        try:
            result = self._parse_json_objects_individually(content)
            if result:
                logger.info(f"[StoryboardDirector] 逐个对象解析成功: {len(result)} 项")
                return result
        except Exception as e:
            logger.debug(f"[StoryboardDirector] 逐个对象解析失败: {e}")
        
        logger.error(f"[StoryboardDirector] JSON 解析最终失败")
        logger.error(f"[StoryboardDirector] 内容前 500 字符: {content[:500] if content else 'EMPTY'}")
        return None
    
    def _fix_json_brackets(self, content: str) -> List[Dict]:
        """修复未闭合的 JSON 括号"""
        # 计算括号平衡
        open_braces = content.count('{')
        close_braces = content.count('}')
        open_brackets = content.count('[')
        close_brackets = content.count(']')
        
        # 补全缺失的括号
        if open_braces > close_braces:
            content = content.rstrip().rstrip(',')
            content += '}' * (open_braces - close_braces)
        
        if open_brackets > close_brackets:
            content = content.rstrip().rstrip(',')
            content += ']' * (open_brackets - close_brackets)
        
        return json.loads(content)
    
    def _parse_json_objects_individually(self, content: str) -> List[Dict]:
        """逐个解析 JSON 对象"""
        import re
        
        # 匹配完整的 JSON 对象
        objects = []
        # 匹配 { ... } 模式，处理嵌套
        depth = 0
        start = None
        
        for i, char in enumerate(content):
            if char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    obj_str = content[start:i+1]
                    try:
                        obj = json.loads(obj_str)
                        objects.append(obj)
                    except json.JSONDecodeError:
                        # 尝试修复单个对象
                        try:
                            fixed = re.sub(r',\s*}', '}', obj_str)
                            obj = json.loads(fixed)
                            objects.append(obj)
                        except:
                            pass
                    start = None
        
        return objects if objects else None


# 便捷函数
async def create_storyboard(state: ComicDramaState) -> Dict[str, Any]:
    """LangGraph node 函数"""
    node = StoryboardDirectorNode()
    return await node.run(state)
