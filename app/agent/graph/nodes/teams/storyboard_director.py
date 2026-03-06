"""
分镜导演节点 - StoryboardDirectorNode

职责：
1. LLM 生成分镜脚本（描述、旁白、时长）→ save_shots Tool 保存

注意：图片提示词生成和图片生成已移至 character_scene_generation_worker 和 shot_generation_worker
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
    
    注意：图片提示词生成和图片生成已移至 character_scene_generation_worker 和 shot_generation_worker
    """
    
    SCRIPT_PROMPT_V1 = """你是一位专业的分镜导演，负责将剧本拆解为详细的分镜脚本。

## 输出格式
返回 JSON 数组，每个分镜包含：

### 基础信息
- scene_name: 所属场景名称（必须与已有场景标题完全一致）
- title: 分镜标题（简短有力，如"初次相遇"、"激烈对峙"）
- characters: 出场角色名称数组（必须与已有角色名称完全一致）
- duration: 预估时长（秒，3-15秒）

### 画面描述（核心字段）
- description: 用自然语言按时间顺序描述这个分镜中发生了什么。
  **写法要求**：
  - 像写剧本动作行一样，用简洁流畅的句子按时间顺序叙述
  - 把场景环境、人物动作、对白内容自然地融合在一起
  - 不要分条目、不要标签、不要维度拆分
  - 不要花哨修辞，只写发生了什么
  - 对白直接写在叙述中，标注谁说了什么

### 对话旁白
- narration: 旁白或对话内容（JSON数组格式：[{"角色": "角色名", "内容": "对话内容"}]）

## 要求
1. 分镜数量控制在 15-30 个
2. 每个分镜时长 3-15 秒
3. **description 是最重要的字段**，必须按时间顺序自然叙述画面中发生的一切
4. 保持剧情连贯性和节奏感
5. 不要添加剧本中没有的情节

## 输出示例
```json
[
    {
        "scene_name": "鱼市",
        "title": "阿九瘫坐鱼摊",
        "characters": ["阿九"],
        "duration": 10,
        "description": "清晨的传统鱼市，薄雾弥漫，摊贩们忙着摆放鲜鱼。阿九穿着油渍斑驳的灰衬衫，瘫坐在鱼摊旁的泡沫箱堆上，肚腩把衬衫扣子绷得紧紧的。他踩着破草鞋，有节奏地拍打着湿漉漉的石板地。腰间一根草绳插着一把断了头的竹木剑，毫不起眼。他眯着眼，嘴角带着一丝似笑非笑的表情，盯着面前的鱼摊发呆。",
        "narration": []
    },
    {
        "scene_name": "鱼市",
        "title": "老王嘲讽",
        "characters": ["老王", "阿九"],
        "duration": 10,
        "description": "隔壁摊位的老王挥着生锈的切鱼刀，一刀砰地剁在木砧板上斩断鱼头。他推了推破旧的圆框眼镜，斜眼看了阿九一眼，边处理鱼边嘲讽道："阿九，隔壁王寡妇家的猫都去抓老鼠了，你倒好，天天在这'我月亮你'地对着鱼摊发呆？"阿九眯眼露出贱萌笑容，微微后仰手搭肚腩："老王，这你就不懂了。我这不是发呆，是'先欠着'。等我攒够了人品，这整条街的鱼都是我的。"",
        "narration": [{"角色": "老王", "内容": "阿九，隔壁王寡妇家的猫都去抓老鼠了，你倒好，天天在这'我月亮你'地对着鱼摊发呆？"}, {"角色": "阿九", "内容": "老王，这你就不懂了。我这不是发呆，是'先欠着'。"}]
    },
    {
        "scene_name": "咖啡厅",
        "title": "午后邂逅",
        "characters": ["林晚"],
        "duration": 5,
        "description": "午后的咖啡厅，阳光从落地窗斜射进来。林晚独自坐在靠窗的位置，穿着浅色毛衣，双手捧着咖啡杯，目光出神地望向窗外的街景。",
        "narration": [{"角色": "旁白", "内容": "那是一个看似平凡的午后"}]
    },
    {
        "scene_name": "咖啡厅",
        "title": "眼神交汇",
        "characters": ["林晚", "李明"],
        "duration": 4,
        "description": "咖啡厅门口传来推门声，林晚下意识转头看去。她的眼神从恍惚变为惊讶，愣在原地，轻声说道："是...你？"",
        "narration": [{"角色": "林晚", "内容": "是...你？"}]
    }
]
```

只输出 JSON，不要其他内容。"""
    # 生成分镜脚本的提示词
    SCRIPT_PROMPT = """你是一位专业的分镜导演，负责将剧本拆解为详细的分镜脚本。

## 输出格式
返回 JSON 数组，每个分镜包含：

### 基础信息
- scene_name: 所属场景名称（必须与已有场景标题完全一致）
- title: 分镜标题（简短有力，如"初次相遇"、"激烈对峙"）
- characters: 出场角色名称数组（必须与已有角色名称完全一致）
- duration: 预估时长（秒，3-8秒）

### 画面描述（核心字段，越详细越好）
- description: 综合画面描述，需包含以下维度：
  1. **场景环境**: 具体地点、空间特征（如"宽敞的现代咖啡厅"）
  2. **空间布局**: 物体摆放、空间层次（如"吧台在左侧，落地窗在右侧"）
  3. **人物位置**: 角色在画面中的位置和朝向（如"女主位于画面中央偏右，面朝窗外"）
  4. **人物状态**: 动作、姿态、表情、视线方向（如"双手捧着咖啡杯，眼神迷离"）
  5. **天气光线**: 时间、天气、光源、光影效果（如"午后阳光斜照，形成温暖的逆光轮廓"）
  6. **情绪氛围**: 整体氛围、色调倾向（如"温馨惬意的午后氛围"）

### 镜头建议（辅助后续生图）
- shot_type: 景别建议（远景/全景/中景/近景/特写）
- camera_angle: 机位角度（平视/俯视/仰视/侧面）

### 对话旁白
- narration: 旁白或对话内容（JSON数组格式：[{"角色": "角色名", "内容": "对话内容"}]）

## 要求
1. 分镜数量控制在 15-30 个
2. 每个分镜时长 3-8 秒
3. **description 字段是最重要的，必须从多个维度详细描述画面**
4. 保持剧情连贯性和节奏感
5. 景别要有变化，避免单调（远→近→特写→中景...）
6. 情绪转折处可用特写强调

## 输出示例
```json
[
    {
        "scene_name": "咖啡厅",
        "title": "午后邂逅",
        "characters": ["林晚"],
        "duration": 5,
        "description": "现代风格的咖啡厅内，暖色调的木质装潢。落地窗外是繁忙的都市街景。林晚独自坐在靠窗的双人座位，身体微微侧向窗外。她穿着浅色毛衣，双手捧着白色咖啡杯，目光出神地望向窗外。午后三点的阳光斜射进来，在她的侧脸形成温柔的光晕。整体氛围宁静而略带忧郁。",
        "shot_type": "中景",
        "camera_angle": "侧面平视",
        "narration": [{"角色": "旁白", "内容": "那是一个看似平凡的午后"}]
    },
    {
        "scene_name": "咖啡厅",
        "title": "眼神交汇",
        "characters": ["林晚", "李明"],
        "duration": 4,
        "description": "林晚的眼睛特写，瞳孔中倒映着门口的人影。她的眼神从恍惚变为惊讶，睫毛微微颤动。柔和的侧光勾勒出眼眶的轮廓，眼眶微微泛红。",
        "shot_type": "特写",
        "camera_angle": "平视",
        "narration": [{"角色": "林晚", "内容": "是...你？"}]
    }
]
```

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
        检查当前分镜进度
        
        Returns:
            {
                "total_shots": int,
                "has_shots": bool,
            }
        """
        result = await query_shots.ainvoke({
            "creation_uuid": creation_uuid,
            "include_details": False,
        })
        
        total = result.get("total", 0)
        
        logger.info(f"[StoryboardDirector] 进度检查: total={total}")
        
        return {
            "total_shots": total,
            "has_shots": total > 0,
        }
    
    async def run(self, state: ComicDramaState) -> Dict[str, Any]:
        """
        执行分镜创建
        
        只负责生成分镜脚本，不生成提示词和图片
        """
        creation_uuid = state.get("creation_uuid")
        script_text = state.get("script_text")
        
        if not script_text:
            return {
                "response_text": "请先上传剧本内容。",
                "production_stage": ProductionStage.INIT,
            }
        
        try:
            from app.agent.tools.db_tools import (
                query_scene_titles, save_shots, query_shots
            )
            
            # ========== 检查当前进度 ==========
            progress = await self._check_progress(creation_uuid, query_shots)
            logger.info(f"[StoryboardDirector] 进度检查: {progress}")
            
            # 如果已有分镜，直接返回成功
            if progress["has_shots"]:
                shot_count = progress["total_shots"]
                logger.info(f"[StoryboardDirector] 已有 {shot_count} 个分镜，跳过生成")
                
                response_text = f"""✅ **分镜脚本已存在！**

📋 **分镜数量**: {shot_count} 个

分镜脚本已生成，请继续下一步操作。"""
                return {
                    "response_text": response_text,
                    "production_stage": ProductionStage.STORYBOARD_READY,
                    "worker_result": {"worker": "storyboard_director", "completed": True, "response_text": response_text},
                    "board_actions": [
                        {"type": "switch_view", "target": "storyboards"},
                        {"type": "refresh"},
                    ],
                }
            
            # ========== Step 1: LLM 生成分镜脚本 ==========
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
                SystemMessage(content=self.SCRIPT_PROMPT_V1),
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
            
            # ========== Step 2: 保存分镜 ==========
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
            
            # ========== 返回成功 ==========
            response_text = f"""✅ **分镜脚本生成完成！**

📋 **分镜数量**: {shot_count} 个

分镜脚本已保存，请继续生成分镜图片。"""
            
            return {
                "response_text": response_text,
                "production_stage": ProductionStage.STORYBOARD_READY,
                "worker_result": {"worker": "storyboard_director", "completed": True, "response_text": response_text},
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
