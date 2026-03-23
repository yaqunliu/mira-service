"""
Vocab Worker - 英语单词视频生成 Worker (ReAct Agent 版本)

新流程：
1. 翻译和分析单词
2. 批量创建分镜
3. 批量生成图片提示词 → 批量生成图片
4. 批量生成视频提示词 → 批量生成视频
5. 导出最终视频
"""

import asyncio
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
        config = state.get("vocab_config", {})
        self.config = merge_vocab_config(config)
        
        word_repeat_count = self.config.get("word_repeat_count", 2)
        translation_repeat_count = self.config.get("translation_repeat_count", 1)
        voice_gender = self.config.get("voice_gender", "female")
        voice_age = self.config.get("voice_age", "child")
        
        creation_uuid = state.get("creation_uuid", "")
        
        return f"""你是英语单词视频生成专家。

### 当前任务信息
- 任务ID (creation_uuid): {creation_uuid}
- 单词朗读次数：{word_repeat_count} 次
- 翻译朗读次数：{translation_repeat_count} 次
- 音色要求：{voice_gender}声，{voice_age}音色

### 你的职责
为每个单词创建视频分镜，包括：
- 分镜1（单词展示）：绚烂背景 + 单词 + 翻译 + 名词图标
- 分镜2（句子场景）：角色在场景中展示句子

### 新流程（必须按顺序执行）
1. 翻译和分析每个单词
2. **调用 get_character_info 获取角色信息（包含 image_url）**
3. 为每个单词生成2个分镜数据（包含 image_prompt 和 video_prompt）
4. 调用 create_shots_batch 批量创建分镜（**sentence_scene 必须传入 reference_images**）
5. 调用 generate_images_batch 批量生成图片（等待完成）
6. 调用 generate_videos_batch 批量生成视频（自动等待完成并导出最终视频）
7. 任务完成

### 可用工具
- get_character_info: 获取角色信息（用于图片生成时的角色参考）
- create_shots_batch: 批量创建分镜（同时保存 image_prompt 和 video_prompt）
- generate_images_batch: 批量生成图片（**必须等待图片生成完成后再执行下一步**）
- generate_videos_batch: 批量生成视频（**自动等待完成并导出最终视频，不需要再调用 export_final_video**）
- update_task_progress: 更新任务进度
- export_final_video: 导出最终视频

### 查询工具
- get_shot_status: 获取所有分镜的生成状态（查看哪些成功/失败）
- get_shot_by_word: 根据单词查询特定分镜的详细信息（用于回答用户关于特定单词的问题）

### 失败重试和重新生成工具
- retry_failed_shots: 重试失败的分镜（stage="image" 或 "video"）
- regenerate_shot_image: 重新生成指定分镜的图片（可提供新提示词）
- regenerate_shot_video: 重新生成指定分镜的视频（可提供新提示词）
- continue_from_current_stage: 断点续传（从当前阶段继续执行）

### 失败处理流程

**当用户说"图片生成失败了"、"视频生成失败了"、"重试"、"继续生成"时：**

1. **首先调用 get_shot_status 查看当前分镜状态**
2. **根据状态决定下一步：**
   - 如果有失败的图片 → 调用 retry_failed_shots(stage="image")
   - 如果有失败的视频 → 调用 retry_failed_shots(stage="video")
   - 如果不确定状态 → 调用 continue_from_current_stage 自动继续

**情况1：图片生成失败**
```
用户: "图片生成失败了" 或 "重试失败的图片"
AI: 
  1. 调用 get_shot_status 查看状态
  2. 调用 retry_failed_shots(stage="image") 重试
  3. 返回结果给用户
```

**情况2：视频生成失败**
```
用户: "视频生成失败了" 或 "重试失败的视频"
AI:
  1. 调用 get_shot_status 查看状态
  2. 调用 retry_failed_shots(stage="video") 重试
  3. 返回结果给用户
```

**情况3：流程中断后继续**
```
用户: "继续生成" 或 "从当前阶段继续"
AI:
  调用 continue_from_current_stage 自动从当前阶段继续执行
  - 如果有分镜但没有图片 → 生成图片
  - 如果有图片但没有视频 → 生成视频
  - 如果有视频 → 导出最终视频
```

**情况4：用户对某个分镜不满意**
```
用户: "重新生成第3个分镜的图片" 或 "第5个分镜视频不好看"
AI:
  调用 regenerate_shot_image(shot_id=3) 或 regenerate_shot_video(shot_id=5)
  可以提供新的提示词来改进生成效果
```

**情况5：查询特定单词的分镜状态**
```
用户: "noodles 分镜处理的结果是什么？" 或 "apple 这个单词的图片生成了吗？"
AI:
  1. 调用 get_shot_by_word(word="noodles") 查询该单词的所有分镜
  2. 根据返回结果回答用户：
     - 如果 found=True：告诉用户该单词有几个分镜，每个分镜的状态、是否有图片/视频
     - 如果 found=False：告诉用户未找到该单词，并列出可用的单词
```

**重要：不要直接显示配置卡片让用户重新配置参数，而是使用重试工具解决问题！**

### 图片生成提示词格式

#### 一张单词展示图 (word_display)
- 绚烂多彩背景
- 白色单词 + 黄色翻译 文字不带有任何括号
- 如果是名词，右上角显示物品简笔画

#### 句子场景图 (sentence_scene)
- 调用 get_character_info 获取角色
- **【关键】必须将角色的 image_url 作为 reference_images 传入 create_shots_batch**
- 图片中需要出现角色（使用角色的 image_url 作为参考图）
- 图片内容要能展示句子含义
- **重要：视频中必须朗读句子内容**

### 分镜类型和图片提示词格式

#### 分镜1：单词展示图 (word_display)
```
【重要】图片提示词格式：
绚烂的多彩背景，有彩色泡泡在缓慢移动。没有固定主体。
**文字位置**：中心位置用白色非衬线体单词写着无括号包裹的「英文单词」，单词下面是翻译。文字占据画面大半部分区域。
【如果是名词，右上角出现圆圈（白色背景），圆圈中是具体的名词物品简笔画】。
文字全程固定出现在视频中，不要消失或移动。纯文字格式无括号

【重要】视频提示词格式：
**文字位置**：单词和翻译固定显示在视频中央，全程不消失。
画面：详细描述整个视频的画面内容，包括角色动作、表情、场景变化等。画面稳定不闪烁。
旁白朗读：根据当前配置「单词朗读{word_repeat_count}次，翻译朗读{translation_repeat_count}次」
```

#### 分镜2：句子场景图 (sentence_scene)
```
注意：画面内容完全符合英文句子大意，不能有任何偏差。而且动作要流畅自然。
【重要】图片提示词格式：
图片内容描述：详细描述出现的场景、地点、人物、动作等。
图片中出现的文字：一行英文句子，黑色粗体带有白色边框，内容是 「...」 固定显示在图片顶部，居中显示。

【重要】视频提示词格式：
**文字位置**：一行英文句子，黑色粗体带有白色边框，内容是  「...」 出现并固定显示在视频顶部居中显示，持续4s(秒)，全程不消失。
画面：详细描述整个视频的画面内容如：什么人物在做什么事情。包括场景、人物、动作、表情变化等。不要描述成静态画面。还有画面需要人物动作流畅。
旁白朗读：**重要**：朗读在视频开始时立即出现，完整朗读句子内容。朗读音色符合画面中的人物。

【关键】创建 sentence_scene 分镜时，必须传入 reference_images！
示例：
create_shots_batch([
    {{
        "word": "food",
        "shot_type": "sentence_scene",
        "sentence": "I like food.",
        "image_prompt": "...",
        "video_prompt": "...",
        "reference_images": ["https://novel-agent.cn-sh2.ufileos.com/test/custom_path/团子.png"]  // 使用角色的 image_url
    }}
])
```

### 视频提示词中朗读内容的 Few-Shot 示例

根据当前配置「单词朗读{word_repeat_count}次，翻译朗读{translation_repeat_count}次」，视频提示词中的朗读内容格式如下：

**示例1：单词展示分镜（word_display）**
- 单词：apple，翻译：苹果
- 配置：单词读2次，翻译读1次
- 视频提示词中的朗读内容：`视频中有一个温柔的人声朗读：apple, apple. 苹果。朗读速度中等，发音准确咬字清晰，接近播音员水平。`

**示例2：单词展示分镜（word_display）**
- 单词：dog，翻译：狗
- 配置：单词读2次，翻译读2次
- 视频提示词中的朗读内容：`视频中有一个温柔的人声朗读：dog, dog. 狗, 狗。朗读速度中等，发音准确咬字清晰，接近播音员水平。`

**示例3：单词展示分镜（word_display）**
- 单词：cat，翻译：猫
- 配置：单词读3次，翻译读1次
- 视频提示词中的朗读内容：`视频中有一个温柔的人声朗读：cat, cat, cat. 猫。朗读速度中等，发音准确咬字清晰，接近播音员水平。`

**示例4：句子场景分镜（sentence_scene）**
- 句子：I like dog!
- 视频提示词中的朗读内容：`视频中有一个温柔的人声朗读句子：I like dog! 朗读速度中等，发音准确咬字清晰，接近播音员水平。`

### 重要规则

1. **朗读内容格式**：
   - 单词展示分镜：`视频中有一个温柔的人声朗读：[单词重复N次], [翻译重复M次]。朗读速度中等，发音准确咬字清晰，接近播音员水平。`
   - 句子场景分镜：`视频中有一个温柔的人声朗读句子：[完整句子] 朗读速度中等，发音准确咬字清晰，接近播音员水平。`

2. **当前任务配置**（单词{word_repeat_count}次，翻译{translation_repeat_count}次）：
   - 每个单词展示分镜的朗读内容必须遵循此配置
   - 句子场景分镜直接朗读完整句子

3. **音色要求**：使用{voice_gender}声，{voice_age}音色

### 重要提示
- 单词展示视频时长固定为 4 秒
- 句子场景视频时长 4 秒
- 书写提示词的时候 单词和句子用 「...」 包裹
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
        # video_model = self.config.get("video_model", "viduq3-pro")
        video_model = self.config.get("video_model", "")
        word_repeat_count = self.config.get("word_repeat_count", 2)
        translation_repeat_count = self.config.get("translation_repeat_count", 1)
        
        return f"""请为以下单词创建视频：

单词列表：{words}
配置：
- 句子难度：{sentence_level}
- 声音：{voice_gender} {voice_age}
- 视频模型：{video_model}
- 单词朗读次数：{word_repeat_count} 次
- 翻译朗读次数：{translation_repeat_count} 次

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
            
            【重要】返回的角色信息包含 image_url，必须将其作为 reference_images 传入 create_shots_batch！
            
            使用示例：
            1. 调用 get_character_info 获取角色
            2. 从返回结果中提取 character.image_url
            3. 创建 sentence_scene 分镜时，将 image_url 放入 reference_images 数组
            
            Args:
                sentence_level: 句子难度 (kindergarten, primary, middle)
                gender: 声音性别偏好 (female, male, None表示随机)
            
            Returns:
                {
                    "character": {
                        "id": "char_001",
                        "name": "团子",
                        "image_url": "https://...",  // 【重要】必须作为 reference_images 使用
                        ...
                    },
                    "scene": {...}
                }
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
        async def create_shots_batch(shots_data) -> Dict:
            """
            批量创建分镜
            
            【重要】sentence_scene 类型的分镜必须传入 reference_images！
            reference_images 应该是角色的 image_url，用于保持角色一致性。
            
            Args:
                shots_data: 分镜数据列表（可以是 JSON 字符串或列表），每个包含:
                    - word: 单词
                    - translation: 中文翻译
                    - sentence: 英文句子
                    - shot_type: 分镜类型 (word_display 或 sentence_scene)
                    - audio_text: 音频文本
                    - duration: 视频时长(默认4秒)
                    - image_prompt: 图片生成提示词
                    - video_prompt: 视频生成提示词（必须提供，为所有分镜类型生成）
                    - reference_images: 参考图片URL列表（**sentence_scene 必须传入角色的 image_url**）
            
            Returns:
                {"success": True, "shot_ids": [1,2,3...], "count": N}
            """
            # 解析 JSON 字符串
            if isinstance(shots_data, str):
                try:
                    import json
                    shots_data = json.loads(shots_data)
                    logger.info(f"[VocabWorker] 解析 shots_data 字符串成功: {len(shots_data)} 个")
                except Exception as e:
                    logger.error(f"[VocabWorker] 解析 shots_data 失败: {e}")
                    return {"error": f"解析 shots_data 失败: {e}"}
            
            # 确保是列表
            if not isinstance(shots_data, list):
                return {"error": f"shots_data 必须是列表类型"}
            
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
        async def save_image_prompts_batch(shots_data) -> Dict:
            """
            批量保存图片提示词
            
            Args:
                shots_data: 提示词数据列表（可以是 JSON 字符串或列表），每个包含:
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
            
            if not isinstance(shots_data, list):
                return {"error": f"shots_data 必须是列表类型"}
            
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
        async def save_video_prompts_batch(shots_data) -> Dict:
            """
            批量保存视频提示词
            
            Args:
                shots_data: 提示词数据列表（可以是 JSON 字符串或列表），每个包含:
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
            
            if not isinstance(shots_data, list):
                return {"error": f"shots_data 必须是列表类型"}
            
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
        async def generate_videos_batch(shot_ids: List[int], model: str = "sora-2") -> Dict:
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
                    creation_id=self.creation_id,
                    model_name=model,
                    separate_audio=False,
                )
                logger.info(f"[VocabWorker] 提交视频生成任务: shot_id={shot_id}, creation_id={self.creation_id}, model={model}")
            
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
                    video_url = result.get("video_url", "")[:100] if result.get("video_url") else "无"
                    status_msg = f"视频生成并导出完成: video_url={video_url}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        status="completed",
                        progress=100,
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
        async def export_final_video(shot_ids: List[int]) -> Dict:
            """
            导出最终视频
            
            Args:
                shot_ids: 分镜ID列表
                
            注意：creation_uuid 会自动从系统上下文获取，不需要手动传入
            """
            logger.info(f"[VocabWorker] 导出最终视频")
            
            from app.agent.tools.export_video_tool import export_final_video
            
            result = await export_final_video.ainvoke({
                "creation_uuid": self.creation_uuid,
                "shot_ids": shot_ids,
            })
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    video_url = result.get("video_url", "")[:100] if result.get("video_url") else "无"
                    status_msg = f"调用工具 export_final_video: shot_ids={shot_ids}, video_url={video_url}"
                    await _update_creation_status(
                        creation_id=self.task_id,
                        current_step="导出视频",
                        status="completed",
                        progress=100,
                        step_status=status_msg,
                    )
                except:
                    pass
            
            return result
        
        @tool
        async def get_shot_status() -> Dict:
            """
            获取所有分镜的生成状态
            
            Returns:
                {"shots": [{"shot_id": 1, "word": "apple", "status": "completed", "image_url": "...", "video_url": "..."}]}
            """
            from app.db.base import _get_async_session_factory
            from app.models.shot import Shot
            from sqlalchemy import select
            
            db = _get_async_session_factory()()
            try:
                result = await db.execute(
                    select(Shot).where(Shot.creation_id == self.creation_id)
                )
                shots = result.scalars().all()
                
                shot_list = []
                for s in shots:
                    extra = s.extra_data or {}
                    shot_list.append({
                        "shot_id": s.shot_id,
                        "word": extra.get("word", ""),
                        "translation": extra.get("translation", ""),
                        "shot_type": extra.get("shot_type", ""),
                        "status": s.status,
                        "has_image": bool(s.image_url),
                        "has_video": bool(s.video_url),
                        "image_url": s.image_url,
                        "video_url": s.video_url,
                    })
                
                logger.info(f"[VocabWorker] 获取分镜状态: {len(shot_list)} 个分镜")
                
                return {"shots": shot_list, "count": len(shot_list)}
            finally:
                await db.close()
        
        @tool
        async def get_shot_by_word(word: str) -> Dict:
            """
            根据单词查询特定分镜的详细信息
            
            用于回答用户关于特定单词分镜的问题，如：
            - "noodles 分镜处理的结果是什么？"
            - "apple 这个单词的图片生成了吗？"
            - "查看 banana 分镜的状态"
            
            Args:
                word: 要查询的单词（英文）
            
            Returns:
                {
                    "found": True,
                    "word": "noodles",
                    "shots": [
                        {
                            "shot_id": 5,
                            "shot_type": "word_display",
                            "status": "completed",
                            "image_url": "...",
                            "video_url": "...",
                            "image_prompt": "...",
                            "video_prompt": "..."
                        },
                        {
                            "shot_id": 6,
                            "shot_type": "sentence_scene",
                            "status": "completed",
                            ...
                        }
                    ]
                }
            """
            from app.db.base import _get_async_session_factory
            from app.models.shot import Shot
            from sqlalchemy import select, or_
            
            logger.info(f"[VocabWorker] 查询单词分镜: word={word}")
            
            db = _get_async_session_factory()()
            try:
                # 查询所有分镜，然后在 Python 中过滤（因为 word 存储在 extra_data JSON 中）
                result = await db.execute(
                    select(Shot).where(Shot.creation_id == self.creation_id)
                )
                shots = result.scalars().all()
                
                # 查找匹配的分镜
                matching_shots = []
                word_lower = word.lower().strip()
                
                for s in shots:
                    extra = s.extra_data or {}
                    shot_word = extra.get("word", "").lower().strip()
                    
                    # 匹配单词（支持部分匹配）
                    if shot_word == word_lower or word_lower in shot_word or shot_word in word_lower:
                        matching_shots.append({
                            "shot_id": s.shot_id,
                            "shot_type": extra.get("shot_type", ""),
                            "word": extra.get("word", ""),
                            "translation": extra.get("translation", ""),
                            "sentence": extra.get("sentence", ""),
                            "status": s.status,
                            "image_url": s.image_url,
                            "video_url": s.video_url,
                            "image_prompt": s.image_prompt,
                            "video_prompt": extra.get("video_prompt", ""),
                            "has_image": bool(s.image_url),
                            "has_video": bool(s.video_url),
                        })
                
                if not matching_shots:
                    # 如果没有精确匹配，返回所有分镜让用户查看
                    all_words = list(set([s.extra_data.get("word", "") for s in shots if s.extra_data]))
                    return {
                        "found": False,
                        "word": word,
                        "message": f"未找到单词 '{word}' 的分镜",
                        "available_words": all_words,
                        "suggestion": f"可用的单词有: {', '.join(all_words[:10])}..." if all_words else "暂无分镜数据"
                    }
                
                # 按 shot_type 排序（word_display 在前，sentence_scene 在后）
                matching_shots.sort(key=lambda x: 0 if x["shot_type"] == "word_display" else 1)
                
                logger.info(f"[VocabWorker] 找到 {len(matching_shots)} 个分镜 for word={word}")
                
                return {
                    "found": True,
                    "word": word,
                    "shots": matching_shots,
                    "summary": {
                        "total_shots": len(matching_shots),
                        "has_all_images": all(s["has_image"] for s in matching_shots),
                        "has_all_videos": all(s["has_video"] for s in matching_shots),
                        "status": "completed" if all(s["has_video"] for s in matching_shots) else "in_progress"
                    }
                }
            finally:
                await db.close()
        
        @tool
        async def retry_failed_shots(stage: str = "image") -> Dict:
            """
            重试失败的分镜
            
            Args:
                stage: 重试阶段 ("image" 或 "video")
            
            Returns:
                {"success": True, "retried_count": N, "shot_ids": [...]}
            """
            from app.db.base import _get_async_session_factory
            from app.models.shot import Shot
            from sqlalchemy import select
            
            db = _get_async_session_factory()()
            try:
                result = await db.execute(
                    select(Shot).where(Shot.creation_id == self.creation_id)
                )
                shots = result.scalars().all()
                
                failed_shot_ids = []
                for s in shots:
                    if stage == "image":
                        if not s.image_url or s.status == "failed":
                            failed_shot_ids.append(s.shot_id)
                            s.status = "pending"
                            await db.commit()
                    elif stage == "video":
                        if not s.video_url or s.status == "failed":
                            failed_shot_ids.append(s.shot_id)
                            s.status = "pending"
                            await db.commit()
                
                logger.info(f"[VocabWorker] 重试失败分镜: stage={stage}, count={len(failed_shot_ids)}")
                
                if not failed_shot_ids:
                    return {"success": True, "retried_count": 0, "message": "没有失败的分镜"}
                
                if stage == "image":
                    for shot_id in failed_shot_ids:
                        from app.tasks.shot_task import generate_single_shot_image_task
                        generate_single_shot_image_task.delay(
                            shot_id=shot_id,
                            creation_id=self.creation_id,
                            frame_type="start"
                        )
                    await self._wait_images_generated(failed_shot_ids)
                elif stage == "video":
                    for shot_id in failed_shot_ids:
                        from app.tasks.step8_video_gen_task import generate_single_shot_video_task
                        generate_single_shot_video_task.delay(
                            shot_id=shot_id,
                            creation_id=self.creation_id,
                            model_name=self.config.get("video_model", "sora-2"),
                            separate_audio=False,
                        )
                    await self._wait_videos_generated(failed_shot_ids)
                
                return {"success": True, "retried_count": len(failed_shot_ids), "shot_ids": failed_shot_ids}
            finally:
                await db.close()
        
        @tool
        async def regenerate_shot_image(shot_id: int, new_prompt: str = None) -> Dict:
            """
            重新生成指定分镜的图片
            
            Args:
                shot_id: 分镜ID
                new_prompt: 新的图片提示词（可选，不提供则使用原有提示词）
            
            Returns:
                {"success": True, "shot_id": N}
            """
            from app.db.base import _get_async_session_factory
            from app.models.shot import Shot
            from sqlalchemy import select
            
            logger.info(f"[VocabWorker] 重新生成图片: shot_id={shot_id}")
            
            db = _get_async_session_factory()()
            try:
                result = await db.execute(
                    select(Shot).where(Shot.shot_id == shot_id)
                )
                shot = result.scalar_one_or_none()
                
                if not shot:
                    return {"success": False, "error": f"分镜不存在: shot_id={shot_id}"}
                
                if new_prompt:
                    shot.image_prompt = new_prompt
                    await db.commit()
                
                shot.status = "pending"
                shot.image_url = None
                await db.commit()
                
                from app.tasks.shot_task import generate_single_shot_image_task
                generate_single_shot_image_task.delay(
                    shot_id=shot_id,
                    creation_id=self.creation_id,
                    frame_type="start"
                )
                
                await self._wait_images_generated([shot_id])
                
                return {"success": True, "shot_id": shot_id}
            finally:
                await db.close()
        
        @tool
        async def regenerate_shot_video(shot_id: int, new_prompt: str = None, model: str = "sora-2") -> Dict:
            """
            重新生成指定分镜的视频
            
            Args:
                shot_id: 分镜ID
                new_prompt: 新的视频提示词（可选，不提供则使用原有提示词）
                model: 视频生成模型
            
            Returns:
                {"success": True, "shot_id": N}
            """
            from app.db.base import _get_async_session_factory
            from app.models.shot import Shot
            from sqlalchemy import select
            from sqlalchemy.orm.attributes import flag_modified
            
            logger.info(f"[VocabWorker] 重新生成视频: shot_id={shot_id}")
            
            db = _get_async_session_factory()()
            try:
                result = await db.execute(
                    select(Shot).where(Shot.shot_id == shot_id)
                )
                shot = result.scalar_one_or_none()
                
                if not shot:
                    return {"success": False, "error": f"分镜不存在: shot_id={shot_id}"}
                
                if new_prompt:
                    extra = shot.extra_data or {}
                    extra["video_prompt"] = new_prompt
                    shot.extra_data = extra
                    flag_modified(shot, "extra_data")
                
                shot.status = "pending"
                shot.video_url = None
                await db.commit()
                
                from app.tasks.step8_video_gen_task import generate_single_shot_video_task
                generate_single_shot_video_task.delay(
                    shot_id=shot_id,
                    creation_id=self.creation_id,
                    model_name=model,
                    separate_audio=False,
                )
                
                await self._wait_videos_generated([shot_id])
                
                return {"success": True, "shot_id": shot_id}
            finally:
                await db.close()
        
        @tool
        async def continue_from_current_stage() -> Dict:
            """
            从当前阶段继续执行（断点续传）
            
            根据当前分镜状态自动判断：
            - 如果有分镜但没有图片 → 生成图片
            - 如果有图片但没有视频 → 生成视频
            - 如果有视频 → 导出最终视频
            
            Returns:
                {"success": True, "stage": "image/video/export", "message": "..."}
            """
            from app.db.base import _get_async_session_factory
            from app.models.shot import Shot
            from sqlalchemy import select
            
            logger.info(f"[VocabWorker] 断点续传检查")
            
            db = _get_async_session_factory()()
            try:
                result = await db.execute(
                    select(Shot).where(Shot.creation_id == self.creation_id)
                )
                shots = result.scalars().all()
                
                if not shots:
                    return {"success": False, "error": "没有分镜，请先创建分镜"}
                
                shot_ids = [s.shot_id for s in shots]
                shots_without_image = [s.shot_id for s in shots if not s.image_url]
                shots_without_video = [s.shot_id for s in shots if not s.video_url]
                
                logger.info(f"[VocabWorker] 分镜状态: 总数={len(shots)}, 无图片={len(shots_without_image)}, 无视频={len(shots_without_video)}")
                
                if shots_without_image:
                    logger.info(f"[VocabWorker] 继续生成图片: {len(shots_without_image)} 个")
                    for shot_id in shots_without_image:
                        from app.tasks.shot_task import generate_single_shot_image_task
                        generate_single_shot_image_task.delay(
                            shot_id=shot_id,
                            creation_id=self.creation_id,
                            frame_type="start"
                        )
                    await self._wait_images_generated(shots_without_image)
                    return {"success": True, "stage": "image", "message": f"已生成 {len(shots_without_image)} 个图片"}
                
                if shots_without_video:
                    logger.info(f"[VocabWorker] 继续生成视频: {len(shots_without_video)} 个")
                    for shot_id in shots_without_video:
                        from app.tasks.step8_video_gen_task import generate_single_shot_video_task
                        generate_single_shot_video_task.delay(
                            shot_id=shot_id,
                            creation_id=self.creation_id,
                            model_name=self.config.get("video_model", "sora-2"),
                            separate_audio=False,
                        )
                    await self._wait_videos_generated(shots_without_video)
                    
                    logger.info(f"[VocabWorker] 视频生成完成，自动导出")
                    from app.agent.tools.export_video_tool import export_final_video
                    result = await export_final_video.ainvoke({
                        "creation_uuid": self.creation_uuid,
                        "shot_ids": shot_ids,
                    })
                    return {"success": True, "stage": "video", "message": f"已生成 {len(shots_without_video)} 个视频", "export_result": result}
                
                logger.info(f"[VocabWorker] 所有分镜已完成，导出最终视频")
                from app.agent.tools.export_video_tool import export_final_video
                result = await export_final_video.ainvoke({
                    "creation_uuid": self.creation_uuid,
                    "shot_ids": shot_ids,
                })
                return {"success": True, "stage": "export", "message": "导出完成", "export_result": result}
            finally:
                await db.close()
        
        return [
            get_character_info,
            create_shots_batch,
            save_image_prompts_batch,
            generate_images_batch,
            save_video_prompts_batch,
            generate_videos_batch,
            update_task_progress,
            export_final_video,
            get_shot_status,
            get_shot_by_word,
            retry_failed_shots,
            regenerate_shot_image,
            regenerate_shot_video,
            continue_from_current_stage,
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
                    creation_type="chat",
                    status="processing",
                    owner_id=self.user_id or 1,
                    extra_data={"video_model": self.config.get("video_model", "sora-2")}
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

    async def _wait_videos_generated(self, shot_ids: List[int], max_wait: int = 3600, interval: int = 10) -> None:
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
        
        # 检查是否有失败的工具调用
        failed_tools = []
        for result in tool_results:
            tool_result = result.get("result", {})
            if isinstance(tool_result, dict) and tool_result.get("error"):
                failed_tools.append({
                    "tool": result.get("tool"),
                    "error": tool_result.get("error")
                })
        
        # 检查是否有失败的分镜（图片或视频生成失败）
        has_failed_shots = False
        failed_shots_info = []
        
        for result in tool_results:
            tool_name = result.get("tool", "")
            tool_result = result.get("result", {})
            
            # 检查 generate_images_batch 或 generate_videos_batch 的结果
            if tool_name in ["generate_images_batch", "generate_videos_batch"]:
                if tool_result.get("failed_count", 0) > 0 or tool_result.get("error"):
                    has_failed_shots = True
                    failed_shots_info.append({
                        "stage": "image" if "image" in tool_name else "video",
                        "count": tool_result.get("failed_count", 0),
                        "error": tool_result.get("error", "")
                    })
        
        # 如果有失败的分镜，返回失败状态并提示用户可以重试
        if has_failed_shots:
            logger.warning(f"[{self.node_name}] 有分镜生成失败: {failed_shots_info}")
            
            if self.task_id:
                try:
                    from app.agent.triggers.vocab_trigger import _update_creation_status
                    await _update_creation_status(
                        creation_id=self.task_id,
                        status="failed",
                        progress=0,
                        current_step=f"部分分镜生成失败，可以使用重试工具继续",
                    )
                except Exception as e:
                    logger.error(f"[{self.node_name}] 更新失败状态失败: {e}")
            
            # 构建失败信息
            failed_stages = [info["stage"] for info in failed_shots_info]
            has_image_failed = "image" in failed_stages
            has_video_failed = "video" in failed_stages
            
            # 构建重试选项
            retry_options = []
            if has_image_failed:
                retry_options.append({"id": "retry_image", "label": "🔄 重试失败的图片", "value": "重试失败的图片"})
            if has_video_failed:
                retry_options.append({"id": "retry_video", "label": "🔄 重试失败的视频", "value": "重试失败的视频"})
            retry_options.append({"id": "continue", "label": "▶️ 继续生成", "value": "继续生成"})
            retry_options.append({"id": "check_status", "label": "📊 查看分镜状态", "value": "查看分镜状态"})
            
            return {
                "success": False,
                "error": f"部分分镜生成失败: {failed_shots_info}",
                "failed_shots": failed_shots_info,
                "can_retry": True,
                "retry_tools": ["retry_failed_shots", "continue_from_current_stage"],
                "message": "部分分镜生成失败，请选择操作：",
                "board_actions": [{
                    "type": "retry_actions",
                    "message": f"检测到 {len(failed_shots_info)} 个分镜生成失败。您可以选择重试失败的资源，或者继续生成流程。",
                    "options": retry_options,
                }],
            }
        
        # 如果有工具执行失败
        if failed_tools and self.task_id:
            error_msg = "; ".join([f"{t['tool']}: {t['error'][:30]}" for t in failed_tools])
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
                "can_retry": True,
                "message": "执行过程中出现错误，请选择操作：",
                "board_actions": [{
                    "type": "retry_actions",
                    "message": f"执行过程中出现错误: {error_msg}。您可以尝试继续生成，或者查看分镜状态了解当前进度。",
                    "options": [
                        {"id": "continue", "label": "▶️ 继续生成", "value": "继续生成"},
                        {"id": "check_status", "label": "📊 查看分镜状态", "value": "查看分镜状态"},
                    ],
                }],
            }
        
        video_url = ""
        for result in tool_results:
            tool_name = result.get("tool", "")
            tool_result = result.get("result", {})
            
            # 1. 直接调用 export_final_video 工具
            if tool_name == "export_final_video":
                video_url = tool_result.get("video_url", "")
                break
            
            # 2. generate_videos_batch 工具内部调用了 export_final_video
            if tool_name == "generate_videos_batch":
                export_result = tool_result.get("export_result", {})
                if export_result:
                    video_url = export_result.get("video_url", "")
                    if video_url:
                        break
        
        logger.info(f"[{self.node_name}] 提取的视频URL: {video_url}")
        
        return {
            "final_video_url": video_url,
            "shots": self.all_shots,
            "current_stage": ProductionStage.COMPLETED,
        }


vocab_worker = VocabWorkerNode()
