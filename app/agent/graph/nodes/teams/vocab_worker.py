"""
Vocab Worker - 英语单词视频生成 Worker (ReAct Agent 版本)

新流程：
1. 翻译和分析单词
2. 批量创建分镜
3. 批量生成图片提示词 → 批量生成图片
4. 批量生成视频提示词 → 批量生成视频
5. 导出最终视频
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage

from app.agent.state.schemas import ComicDramaState, ProductionStage
from app.agent.graph.nodes.teams.react_worker_base import ReActWorkerNode
from app.agent.config.vocab_config import (
    merge_vocab_config, 
    select_character, 
    select_scene,
)
from app.core.logger import logger
from app.core.config import settings


class VocabWorkerNode(ReActWorkerNode):
    """英语单词视频生成 Worker - ReAct Agent 模式"""

    USE_REACT = True

    def __init__(self):
        super().__init__(model="MiniMax-M2.5", temperature=0.5)
        self.node_name = "VocabWorker"
        self.creation_uuid = "vocab_default"
        self.creation_id = None
        self.user_id = None
        self.task_id = None
        self.config = {}
        self.all_shots = []

    def get_system_prompt(self, state: ComicDramaState) -> str:
        return """你是英语单词视频生成专家。

### 你的职责
为每个单词创建视频分镜，包括：
- 分镜1（单词展示）：绚烂背景 + 单词 + 翻译 + 名词图标
- 分镜2（句子场景）：角色在场景中展示句子

### 新流程（必须按顺序执行）
1. 翻译和分析每个单词
2. 为每个单词生成2个分镜数据（包含 image_prompt 和 video_prompt）
3. 调用 create_shots_batch 批量创建分镜（同时保存提示词）
4. 调用 generate_images_batch 批量生成图片（等待完成）
5. 调用 generate_videos_batch 批量生成视频（自动等待完成并导出最终视频）
6. 任务完成

### 可用工具
- get_character_info: 获取角色信息（用于图片生成时的角色参考）
- create_shots_batch: 批量创建分镜（同时保存 image_prompt 和 video_prompt）
- generate_images_batch: 批量生成图片（**必须等待图片生成完成后再执行下一步**）
- generate_videos_batch: 批量生成视频（**自动等待完成并导出最终视频，不需要再调用 export_final_video**）
- update_task_progress: 更新任务进度
- export_final_video: 导出最终视频

### 图片生成提示词格式

#### 单词展示图 (word_display)
- 绚烂多彩背景
- 白色单词 + 黄色翻译
- 如果是名词，右上角显示物品简笔画

#### 句子场景图 (sentence_scene)
- 调用 get_character_info 获取角色
- 图片中需要出现角色（使用角色的 image_url 作为参考图）
- 图片内容要能展示句子含义
- **重要：视频中必须朗读句子内容**

### 分镜类型和图片提示词格式

#### 分镜1：单词展示图 (word_display)
```
4【重要】图片提示词格式：
绚烂的多彩背景，没有固定主体，只有颜色交织。
**文字位置**：中心位置用白色非衬线体单词写着【英文单词】，单词下面是翻译。
【如果是名词，右上角出现圆圈（白色背景），圆圈中是具体的名词物品简笔画】。
文字全程固定出现在视频中，不要消失或移动。

【重要】视频提示词格式：
**文字位置**：单词和翻译固定显示在视频中央，全程不消失。

全局氛围：绚烂多彩背景，梦幻渐变色调，迪士尼/皮克斯动画风格。

画面：详细描述整个视频的画面内容，包括角色动作、表情、场景变化等。

背景音：描述背景音乐风格，如欢快钢琴曲、梦幻音乐等。

旁白朗读：单词朗读在视频开始时立即出现。格式：
- 单词第1遍：如 "Monday"
- 单词第2遍：如 "Monday"
- 翻译：如 "星期一"
```

#### 分镜2：句子场景图 (sentence_scene)
```
【重要】图片提示词格式：
**文字位置**：句子放在图片顶部，从开始到结束都在画面上方，不能消失或移动。
【重要】句子内容必须写入提示词，如：句子 "Monday is the first day of the week." 全程显示在图片顶部。
图片内容描述：详细描述出现的场景、地点、人物、动作等。

【重要】视频提示词格式：
**文字位置**：句子 "..." 固定显示在视频顶部，全程不消失。

全局氛围：明亮欢快学校场景，蓝天白云，动漫风格，迪士尼/皮克斯风格。

画面：详细描述整个视频的画面内容，包括场景、人物、动作、表情变化等。

背景音：描述背景音乐和环境音，如学校环境音、欢快钢琴背景音乐等。

旁白朗读：**重要**：朗读在视频开始时立即出现，完整朗读句子内容。
```

### 重要提示
- 单词展示视频时长固定为 4 秒
- 句子场景视频时长 4 秒
- 必须使用卡通/动画风格（如迪士尼/皮克斯风格），不要写实风格
- 组句子时：根据单词含义选择正确的动词搭配，确保语法正确
- 星期、月份等词前不加冠词
- generate_images_batch 和 generate_videos_batch 会自动等待完成，**调用后必须等待返回结果才能执行下一步**"""

    def get_user_message(self, state: ComicDramaState) -> str:
        config = state.get("vocab_config", {})
        self.config = merge_vocab_config(config)
        self.task_id = state.get("task_id")
        
        words = self.config.get("words", [])
        sentence_level = self.config.get("sentence_level", "primary")
        voice_gender = self.config.get("voice_gender", "female")
        voice_age = self.config.get("voice_age", "child")
        video_model = self.config.get("video_model", "doubao-seedance-1-5-pro-251215")
        
        return f"""请为以下单词创建视频：

单词列表：{words}
配置：
- 句子难度：{sentence_level}
- 声音：{voice_gender} {voice_age}
- 视频模型：{video_model}

请按照流程：
1. 对每个单词进行翻译和分析
2. 为每个单词创建2个分镜（word_display + sentence_scene）
3. 批量创建分镜
4. 批量生成图片提示词并生成图片
5. 批量生成视频提示词并生成视频
6. 导出最终视频

最终返回所有分镜信息和最终视频URL。"""

    def get_tools(self) -> List:
        from langchain_core.tools import tool
        from app.agent.config.vocab_config import select_character, select_scene
        
        @tool
        async def get_character_info(sentence_level: str = "primary", gender: str = None) -> Dict:
            """
            获取随机角色和场景信息
            
            Args:
                sentence_level: 句子难度 (kindergarten, primary, middle)
                gender: 声音性别偏好 (female, male, None表示随机)
            
            Returns:
                角色和场景信息字典
            """
            logger.info(f"[VocabWorker] 获取角色信息: sentence_level={sentence_level}, gender={gender}")
            
            character = select_character(sentence_level, gender)
            scene = select_scene(sentence_level)
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    status_msg = f"调用工具 get_character_info: sentence_level={sentence_level}, gender={gender}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        current_step="获取角色信息",
                        step_status=status_msg,
                    )
                except:
                    pass
            
            return {
                "character": character,
                "scene": scene,
            }
        
        @tool
        async def create_shots_batch(shots_data: List[Dict]) -> Dict:
            """
            批量创建分镜
            
            Args:
                shots_data: 分镜数据列表，每个包含:
                    - word: 单词
                    - translation: 中文翻译
                    - sentence: 英文句子
                    - shot_type: 分镜类型 (word_display 或 sentence_scene)
                    - audio_text: 音频文本
                    - duration: 视频时长(默认4秒)
                    - image_prompt: 图片生成提示词
                    - video_prompt: 视频生成提示词（必须提供，为所有分镜类型生成）
                    - reference_images: 参考图片URL列表（仅 sentence_scene 需要）
            
            Returns:
                {"success": True, "shot_ids": [1,2,3...], "count": N}
            """
            if isinstance(shots_data, str):
                try:
                    import json
                    shots_data = json.loads(shots_data)
                    logger.info(f"[VocabWorker] 解析 shots_data 字符串成功: {len(shots_data)} 个")
                except Exception as e:
                    logger.error(f"[VocabWorker] 解析 shots_data 失败: {e}")
                    return {"error": f"解析 shots_data 失败: {e}"}
            
            logger.info(f"[VocabWorker] 批量创建分镜: {len(shots_data)} 个")
            
            shot_ids = []
            for shot_data in shots_data:
                shot_id = await self._create_single_shot(shot_data)
                
                image_prompt = shot_data.get("image_prompt")
                if image_prompt:
                    await self._update_shot_prompt(shot_id, "image_prompt", image_prompt)
                
                video_prompt = shot_data.get("video_prompt")
                if video_prompt:
                    await self._update_shot_prompt(shot_id, "video_prompt", video_prompt)
                
                reference_images = shot_data.get("reference_images", [])
                if reference_images:
                    await self._update_shot_extra(shot_id, "reference_images", reference_images)
                
                shot_ids.append(shot_id)
                self.all_shots.append({**shot_data, "shot_id": shot_id})
            
            logger.info(f"[VocabWorker] 分镜创建完成: {shot_ids}")
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    words = [s.get("word", "") for s in shots_data]
                    translations = [s.get("translation", "") for s in shots_data]
                    sentences = [s.get("sentence", "") for s in shots_data]
                    status_msg = f"调用工具 create_shots_batch: 创建 {len(shots_data)} 个分镜, 单词={words}, 翻译={translations}, 句子={sentences}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        current_step="创建分镜",
                        step_status=status_msg,
                    )
                except:
                    pass
            
            return {"success": True, "shot_ids": shot_ids, "count": len(shot_ids)}
        
        @tool
        async def save_image_prompts_batch(shots_data: List[Dict]) -> Dict:
            """
            批量保存图片提示词
            
            Args:
                shots_data: 提示词数据列表，每个包含:
                    - shot_id: 分镜ID
                    - image_type: 图片类型 (word_display 或 sentence_scene)
                    - prompt: 图片提示词
            
            Returns:
                {"success": True, "count": N}
            """
            if isinstance(shots_data, str):
                try:
                    import json
                    shots_data = json.loads(shots_data)
                except Exception as e:
                    return {"error": f"解析 shots_data 失败: {e}"}
            
            logger.info(f"[VocabWorker] 批量保存图片提示词: {len(shots_data)} 个")
            
            for item in shots_data:
                await self._update_shot_prompt(item["shot_id"], "image_prompt", item["prompt"])
                await self._update_shot_extra(item["shot_id"], "image_type", item.get("image_type", ""))
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    shot_ids = [item.get("shot_id") for item in shots_data]
                    prompts_preview = [item.get("prompt", "")[:30] for item in shots_data]
                    status_msg = f"调用工具 save_image_prompts_batch: shot_ids={shot_ids}, 提示词预览={prompts_preview}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        current_step="保存图片提示词",
                        step_status=status_msg,
                    )
                except:
                    pass
            
            return {"success": True, "count": len(shots_data)}
        
        @tool
        async def generate_images_batch(shot_ids: List[int]) -> Dict:
            """
            批量生成图片
            
            Args:
                shot_ids: 分镜ID列表
            
            Returns:
                {"success": True, "count": N}
            """
            if isinstance(shot_ids, str):
                try:
                    import json
                    shot_ids = json.loads(shot_ids)
                except Exception as e:
                    return {"error": f"解析 shot_ids 失败: {e}"}
            
            logger.info(f"[VocabWorker] 批量生成图片: {len(shot_ids)} 个")
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    status_msg = f"调用工具 generate_images_batch: shot_ids={shot_ids}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        status="generating",
                        progress=20,
                        current_step="提交图片生成",
                        step_status=f"{status_msg}\n创建分镜完成",
                    )
                except:
                    pass
            
            for shot_id in shot_ids:
                from app.tasks.shot_task import generate_single_shot_image_task
                generate_single_shot_image_task.delay(
                    shot_id=shot_id,
                    creation_id=self.creation_id,
                    frame_type="start"
                )
                logger.info(f"[VocabWorker] 提交图片生成任务: shot_id={shot_id}")
            
            await self._wait_images_generated(shot_ids)
            
            return {"success": True, "count": len(shot_ids)}
        
        @tool
        async def save_video_prompts_batch(shots_data: List[Dict]) -> Dict:
            """
            批量保存视频提示词
            
            Args:
                shots_data: 提示词数据列表，每个包含:
                    - shot_id: 分镜ID
                    - prompt: 视频提示词
            
            Returns:
                {"success": True, "count": N}
            """
            if isinstance(shots_data, str):
                try:
                    import json
                    shots_data = json.loads(shots_data)
                except Exception as e:
                    return {"error": f"解析 shots_data 失败: {e}"}
            
            logger.info(f"[VocabWorker] 批量保存视频提示词: {len(shots_data)} 个")
            
            for item in shots_data:
                await self._update_shot_prompt(item["shot_id"], "video_prompt", item["prompt"])
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    shot_ids = [item.get("shot_id") for item in shots_data]
                    prompts_preview = [item.get("prompt", "")[:30] for item in shots_data]
                    status_msg = f"调用工具 save_video_prompts_batch: shot_ids={shot_ids}, 提示词预览={prompts_preview}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        current_step="保存视频提示词",
                        step_status=status_msg,
                    )
                except:
                    pass
            
            return {"success": True, "count": len(shots_data)}
        
        @tool
        async def generate_videos_batch(shot_ids: List[int], model: str = "doubao-seedance-1-5-pro-251215") -> Dict:
            """
            批量生成视频
            
            Args:
                shot_ids: 分镜ID列表
                model: 视频生成模型
            
            Returns:
                {"success": True, "count": N}
            """
            if isinstance(shot_ids, str):
                try:
                    import json
                    shot_ids = json.loads(shot_ids)
                except Exception as e:
                    return {"error": f"解析 shot_ids 失败: {e}"}
            
            logger.info(f"[VocabWorker] 批量生成视频: {len(shot_ids)} 个")
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    status_msg = f"调用工具 generate_videos_batch: shot_ids={shot_ids}, model={model}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        status="generating",
                        progress=50,
                        current_step="提交视频生成",
                        step_status=status_msg,
                    )
                except:
                    pass
            
            for shot_id in shot_ids:
                from app.tasks.step8_video_gen_task import generate_single_shot_video_task
                generate_single_shot_video_task.delay(
                    shot_id=shot_id,
                    creation_id=None,
                    model_name=model,
                    separate_audio=False,
                )
                logger.info(f"[VocabWorker] 提交视频生成任务: shot_id={shot_id}, model={model}")
            
            await self._wait_videos_generated(shot_ids)
            
            logger.info(f"[VocabWorker] 视频生成完成，自动导出最终视频")
            
            from app.agent.tools.export_video_tool import export_final_video
            
            logger.info(f"[VocabWorker] 导出最终视频: shot_ids={shot_ids}")
            
            result = await export_final_video.ainvoke({
                "creation_uuid": self.creation_uuid,
                "shot_ids": shot_ids,
            })
            
            logger.info(f"[VocabWorker] 导出结果: {result}")
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    video_url = result.get("video_url", "")[:50] if result.get("video_url") else "无"
                    status_msg = f"视频生成并导出完成: video_url={video_url}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        status="exporting",
                        progress=90,
                        current_step="导出完成",
                        step_status=status_msg,
                    )
                except:
                    pass
            
            return {"success": True, "count": len(shot_ids), "export_result": result}
        
        @tool
        async def update_task_progress(status: str, progress: int, current_step: str) -> Dict:
            """
            更新任务进度状态
            
            Args:
                status: 任务状态
                progress: 进度百分比
                current_step: 当前步骤
            """
            from app.agent.triggers.vocab_trigger import _update_creation_status
            
            if self.task_id:
                status_msg = f"调用工具 update_task_progress: status={status}, progress={progress}, current_step={current_step}"
                await _update_creation_status(
                    creation_id=self.task_id,
                    status=status,
                    progress=progress,
                    current_step=current_step,
                    step_status=status_msg,
                )
                return {"success": True, "status": status, "progress": progress}
            return {"success": False, "message": "task_id not set"}
        
        @tool
        async def export_final_video(creation_uuid: str = None, shot_ids: List[int] = None) -> Dict:
            """
            导出最终视频
            
            Args:
                creation_uuid: 创建项目UUID
                shot_ids: 分镜ID列表
            """
            logger.info(f"[VocabWorker] 导出最终视频")
            
            from app.agent.tools.export_video_tool import export_final_video
            
            result = await export_final_video.ainvoke({
                "creation_uuid": creation_uuid or self.creation_uuid,
                "shot_ids": shot_ids or [s["shot_id"] for s in self.all_shots],
            })
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    video_url = result.get("video_url", "")[:50] if result.get("video_url") else "无"
                    status_msg = f"调用工具 export_final_video: shot_ids={shot_ids or [s['shot_id'] for s in self.all_shots]}, video_url={video_url}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        current_step="导出视频",
                        step_status=status_msg,
                    )
                except:
                    pass
            
            return result
        
        return [
            get_character_info,
            create_shots_batch,
            save_image_prompts_batch,
            generate_images_batch,
            save_video_prompts_batch,
            generate_videos_batch,
            update_task_progress,
            export_final_video,
        ]

    async def _create_single_shot(self, shot_data: Dict) -> int:
        """创建单个分镜"""
        from app.db.base import _get_async_session_factory
        from app.models.creation import Creation
        from app.models.shot import Shot
        from app.models.scene import Scene
        from sqlalchemy import select
        
        creation_uuid = self.creation_uuid
        
        db = _get_async_session_factory()()
        try:
            result = await db.execute(
                select(Creation).where(Creation.uuid == creation_uuid)
            )
            creation = result.scalar_one_or_none()
            
            if not creation:
                creation = Creation(
                    uuid=creation_uuid,
                    title="单词视频",
                    creation_type="vocab",
                    status="processing",
                    owner_id=self.user_id or 1,
                    extra_data={"video_model": self.config.get("video_model", "doubao-seedance-1-5-pro-251215")}
                )
                db.add(creation)
                await db.flush()
                # 保存 creation_id 供后续使用
                self.creation_id = creation.creation_id
            
            scene_result = await db.execute(
                select(Scene).where(
                    Scene.creation_id == creation.creation_id,
                    Scene.title == "default"
                )
            )
            scene = scene_result.scalar_one_or_none()
            
            if not scene:
                scene = Scene(
                    creation_id=creation.creation_id,
                    title="default",
                    location="default",
                )
                db.add(scene)
                await db.flush()
            
            shot = Shot(
                creation_id=creation.creation_id,
                scene_id=scene.scene_id,
                title=shot_data.get("shot_type", "word_display"),
                shot_number=0,
                description="",
                video_duration=shot_data.get("duration", 4),
                extra_data={
                    "word": shot_data.get("word"),
                    "translation": shot_data.get("translation"),
                    "sentence": shot_data.get("sentence"),
                    "audio_text": shot_data.get("audio_text", ""),
                    "duration": shot_data.get("duration", 4),
                    "shot_type": shot_data.get("shot_type"),
                },
                status="pending"
            )
            
            db.add(shot)
            await db.commit()
            await db.refresh(shot)
            
            logger.info(f"[VocabWorker] 创建分镜: shot_id={shot.shot_id}")
            return shot.shot_id
        finally:
            await db.close()

    async def _update_shot_prompt(self, shot_id: int, prompt_type: str, prompt: str):
        """更新分镜提示词"""
        from app.db.base import _get_async_session_factory
        from app.models.shot import Shot
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified
        
        logger.info(f"[VocabWorker] 更新分镜提示词开始: shot_id={shot_id}, type={prompt_type}, prompt长度={len(prompt)}")
        logger.info(f"[VocabWorker] prompt内容: {prompt[:300]}...")
        
        db = _get_async_session_factory()()
        try:
            result = await db.execute(
                select(Shot).where(Shot.shot_id == shot_id)
            )
            shot = result.scalar_one_or_none()
            
            if not shot:
                logger.error(f"[VocabWorker] 分镜不存在: shot_id={shot_id}")
                return
            
            if prompt_type == "image_prompt":
                shot.image_prompt = prompt
                logger.info(f"[VocabWorker] 设置 image_prompt 成功")
            elif prompt_type == "video_prompt":
                extra = shot.extra_data or {}
                extra["video_prompt"] = prompt
                shot.extra_data = extra
                flag_modified(shot, "extra_data")
                logger.info(f"[VocabWorker] 设置 extra_data.video_prompt 成功, extra_data={shot.extra_data}")
            
            await db.commit()
            logger.info(f"[VocabWorker] 更新分镜提示词成功: shot_id={shot_id}, type={prompt_type}")
        except Exception as e:
            logger.error(f"[VocabWorker] 更新分镜提示词失败: shot_id={shot_id}, type={prompt_type}, error={e}", exc_info=True)
        finally:
            await db.close()

    async def _update_shot_extra(self, shot_id: int, key: str, value: Any):
        """更新分镜额外数据"""
        from app.db.base import _get_async_session_factory
        from app.models.shot import Shot
        from sqlalchemy import select
        from sqlalchemy.orm.attributes import flag_modified
        
        logger.info(f"[VocabWorker] _update_shot_extra 开始: shot_id={shot_id}, key={key}, value={value}")
        
        # 如果是 reference_images，清理 URL 中的反引号和空格
        if key == "reference_images" and isinstance(value, list):
            cleaned = []
            for url in value:
                if isinstance(url, str):
                    # 去除首尾空格、反引号、引号
                    cleaned_url = url.strip()
                    cleaned_url = cleaned_url.strip('`').strip('"').strip("'").strip()
                    cleaned.append(cleaned_url)
                else:
                    cleaned.append(url)
            value = cleaned
            logger.info(f"[VocabWorker] 清理后的 reference_images: {value}")
        
        db = _get_async_session_factory()()
        try:
            result = await db.execute(
                select(Shot).where(Shot.shot_id == shot_id)
            )
            shot = result.scalar_one_or_none()
            
            if shot:
                extra = shot.extra_data or {}
                extra[key] = value
                shot.extra_data = extra
                flag_modified(shot, "extra_data")
                await db.commit()
                logger.info(f"[VocabWorker] 更新分镜额外数据成功: shot_id={shot_id}, {key}")
            else:
                logger.warning(f"[VocabWorker] 分镜不存在: shot_id={shot_id}")
        except Exception as e:
            logger.error(f"[VocabWorker] 更新分镜额外数据失败: shot_id={shot_id}, error={e}")
        finally:
            await db.close()

    async def _wait_images_generated(self, shot_ids: List[int], max_wait: int = 600, interval: int = 10) -> None:
        """等待所有图片生成完成"""
        import asyncio
        from app.db.base import _get_async_session_factory
        from app.models.shot import Shot
        from sqlalchemy import select
        
        logger.info(f"[VocabWorker] 等待 {len(shot_ids)} 个图片生成完成")
        
        waited = 0
        while waited < max_wait:
            await asyncio.sleep(interval)
            waited += interval
            
            db = _get_async_session_factory()()
            try:
                result = await db.execute(
                    select(Shot).where(Shot.shot_id.in_(shot_ids))
                )
                shots = result.scalars().all()
                
                completed = sum(1 for s in shots if s.image_url and s.status == "completed")
                failed = sum(1 for s in shots if s.status == "failed")
                
                logger.info(f"[VocabWorker] 图片生成进度: {completed}/{len(shot_ids)}, 失败: {failed}")
                
                if self.task_id and len(shot_ids) > 0:
                    try:
                        from app.agent.triggers.vocab_trigger import _update_creation_status
                        prog = int((completed / len(shot_ids)) * 20)
                        await _update_creation_status(
                            creation_id=self.task_id,
                            status="generating",
                            progress=prog,
                            current_step=f"生成图片 {completed}/{len(shot_ids)}",
                        )
                    except:
                        pass
                
                if completed == len(shot_ids):
                    logger.info(f"[VocabWorker] 所有图片生成完成")
                    return
                
                if failed > 0:
                    logger.warning(f"[VocabWorker] 有 {failed} 个图片生成失败")
            finally:
                await db.close()
        
        logger.error(f"[VocabWorker] 等待图片生成超时")

    async def _wait_videos_generated(self, shot_ids: List[int], max_wait: int = 1800, interval: int = 10) -> None:
        """等待所有视频生成完成"""
        import asyncio
        from app.db.base import _get_async_session_factory
        from app.models.shot import Shot
        from sqlalchemy import select
        
        logger.info(f"[VocabWorker] 等待 {len(shot_ids)} 个视频生成完成")
        
        waited = 0
        while waited < max_wait:
            await asyncio.sleep(interval)
            waited += interval
            
            db = _get_async_session_factory()()
            try:
                result = await db.execute(
                    select(Shot).where(Shot.shot_id.in_(shot_ids))
                )
                shots = result.scalars().all()
                
                completed = sum(1 for s in shots if s.video_url and s.status == "completed")
                failed = sum(1 for s in shots if s.status == "failed")
                
                logger.info(f"[VocabWorker] 视频生成进度: {completed}/{len(shot_ids)}, 失败: {failed}")
                
                for s in shots:
                    logger.info(f"[VocabWorker] 分镜状态: shot_id={s.shot_id}, status={s.status}, video_url={s.video_url}")
                
                if self.task_id and len(shot_ids) > 0:
                    try:
                        from app.agent.triggers.vocab_trigger import _update_creation_status
                        
                        if failed > 0:
                            await _update_creation_status(
                                creation_id=self.task_id,
                                status="failed",
                                progress=0,
                                current_step=f"视频生成失败: {failed}/{len(shot_ids)} 个失败",
                            )
                            return
                        
                        prog = 50 + int((completed / len(shot_ids)) * 40)
                        await _update_creation_status(
                            creation_id=self.task_id,
                            status="generating",
                            progress=prog,
                            current_step=f"生成视频 {completed}/{len(shot_ids)}",
                        )
                    except:
                        pass
                
                if completed == len(shot_ids):
                    logger.info(f"[VocabWorker] 所有视频生成完成")
                    return
            finally:
                await db.close()
        
        logger.error(f"[VocabWorker] 等待视频生成超时")

    async def process_result(self, state: ComicDramaState, final_response: str, tool_results: List[Dict]) -> Dict[str, Any]:
        """处理最终结果"""
        logger.info(f"[{self.node_name}] 处理最终结果")
        
        failed_tools = []
        for result in tool_results:
            tool_result = result.get("result", {})
            if isinstance(tool_result, dict) and tool_result.get("error"):
                failed_tools.append({
                    "tool": result.get("tool"),
                    "error": tool_result.get("error")
                })
        
        if failed_tools and self.task_id:
            error_msg = "; ".join([f"{t['tool']}: {t['error'][:30]}" for t in failed_tools])
            # current_step 字段最大100字符，需要截断
            error_msg = error_msg[:100]
            logger.error(f"[{self.node_name}] 有工具执行失败: {failed_tools}")
            
            try:
                from app.agent.triggers.vocab_trigger import _update_creation_status
                await _update_creation_status(
                    creation_id=self.task_id,
                    status="failed",
                    progress=0,
                    current_step=f"执行失败: {error_msg}",
                )
            except Exception as e:
                logger.error(f"[{self.node_name}] 更新失败状态失败: {e}")
            
            return {
                "success": False,
                "error": f"工具执行失败: {error_msg}",
                "failed_tools": failed_tools,
            }
        
        video_url = ""
        for result in tool_results:
            if result.get("tool") == "export_final_video":
                video_url = result.get("result", {}).get("video_url", "")
                break
        
        return {
            "final_video_url": video_url,
            "shots": self.all_shots,
            "current_stage": ProductionStage.COMPLETED,
        }


vocab_worker = VocabWorkerNode()
