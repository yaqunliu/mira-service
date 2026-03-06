"""
音色选择工具 - Voice Selection Tools

为角色选择 Fish Audio 音色的工具集
支持从 finalfish.json 加载音色并智能匹配
支持重新匹配单个或全部角色
"""

import json
import os
import random
from typing import Dict, Any, List, Optional
from app.agent.tools.base import BaseTool
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.core.config import settings


# 默认音色文件
DEFAULT_VOICE_FILE = "docs/FISH_AUDIO_VOICES_REAL.json"
# 精选音色文件
SELECTED_VOICE_FILE = "docs/finalfish.json"


class LoadVoiceListTool(BaseTool):
    """加载音色列表工具"""

    name = "load_voice_list"
    description = """加载 Fish Audio 可用的音色列表。

功能：
1. 从 finalfish.json 或 FISH_AUDIO_VOICES_REAL.json 加载音色
2. 返回按性别分类的音色信息
3. 支持获取男声、女声或全部音色

返回数据包含：
- voices: 所有音色列表（包含 id, title, description, gender, samples 等）
- male_voices: 男声列表
- female_voices: 女声列表
- statistics: 音色统计信息
"""

    def __init__(self, db_factory=None):
        super().__init__(db_factory)
        self._voice_cache = None

    def _load_voices_from_file(self, use_selected: bool = True) -> Dict[str, Any]:
        """从文件加载音色数据"""
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            
            # 优先使用精选音色文件
            if use_selected:
                selected_path = os.path.join(base_dir, SELECTED_VOICE_FILE)
                if os.path.exists(selected_path):
                    with open(selected_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        voices = data.get("voices", [])
                        logger.info(f"从精选音色文件加载了 {len(voices)} 个音色")
                        return self._categorize_voices(voices)
            
            # 回退到完整音色文件
            cache_path = os.path.join(base_dir, DEFAULT_VOICE_FILE)
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            
            logger.warning(f"音色文件不存在")
            return {"male": [], "female": [], "unknown": []}

        except Exception as e:
            logger.error(f"加载音色列表失败: {e}")
            return {"male": [], "female": [], "unknown": []}
    
    def _categorize_voices(self, voices: List[Dict]) -> Dict[str, List]:
        """按性别分类音色"""
        result = {"male": [], "female": [], "unknown": []}
        for voice in voices:
            gender = voice.get("gender", "unknown")
            if gender in result:
                result[gender].append(voice)
            else:
                result["unknown"].append(voice)
        return result

    def execute(
        self,
        state: ComicDramaState,
        voice_type: str = "all",
        use_selected: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        加载音色列表

        Args:
            state: 当前状态
            voice_type: 音色类型 (all/male/female/unknown)
            use_selected: 是否使用精选音色文件

        Returns:
            音色列表信息
        """
        try:
            data = self._load_voices_from_file(use_selected)

            all_voices = []
            all_voices.extend(data.get("male", []))
            all_voices.extend(data.get("female", []))
            all_voices.extend(data.get("unknown", []))

            filtered_voices = all_voices
            if voice_type == "male":
                filtered_voices = data.get("male", [])
            elif voice_type == "female":
                filtered_voices = data.get("female", [])
            elif voice_type == "unknown":
                filtered_voices = data.get("unknown", [])

            statistics = {
                "total": len(all_voices),
                "male": len(data.get("male", [])),
                "female": len(data.get("female", [])),
                "unknown": len(data.get("unknown", []))
            }

            return {
                "success": True,
                "message": f"加载音色列表成功，共 {len(filtered_voices)} 个音色",
                "data": {
                    "voices": filtered_voices,
                    "voice_type": voice_type,
                    "statistics": statistics,
                    "source": "selected" if use_selected else "full"
                }
            }

        except Exception as e:
            logger.error(f"加载音色列表失败: {e}")
            return {
                "success": False,
                "message": "加载音色列表失败",
                "error": str(e)
            }


class MatchVoiceByDescriptionTool(BaseTool):
    """根据描述匹配音色工具 - 使用 LLM 智能匹配"""

    name = "match_voice_by_description"
    description = """根据角色描述使用 LLM 智能匹配 Fish Audio 音色。

输入参数：
- character_description: 角色描述
- character_name: 角色名称（可选，用于辅助匹配）
- gender: 性别偏好 (male/female/unknown)
- exclude_voice_ids: 排除的音色ID列表（避免重复）

匹配逻辑：
1. 从 finalfish.json 加载精选音色
2. 根据性别筛选
3. 使用 LLM 分析角色特征并选择最合适的音色
4. 返回最佳匹配的音色列表

返回匹配的音色列表（按匹配度排序），包含：
- id, title, description, gender, samples
- match_score: 匹配度 (0-100)
- match_reason: 匹配理由（LLM 分析结果）
"""

    def __init__(self, db_factory=None):
        super().__init__(db_factory)
        self._load_tool = LoadVoiceListTool()
        self._llm = ChatOpenAI(
            model="Qwen/Qwen-Plus",
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.3,
            timeout=30,
            max_retries=2,
        )

    def _build_voice_prompt(self, voices: List[Dict[str, Any]]) -> str:
        """构建音色列表提示"""
        voice_list = []
        for i, voice in enumerate(voices, 1):
            voice_info = f"""
{i}. ID: {voice.get('id', '')}
   名称: {voice.get('title', '')}
   性别: {voice.get('gender', 'unknown')}
   描述: {voice.get('description', '无')[:200]}"""
            voice_list.append(voice_info)
        return "\n".join(voice_list)

    async def _llm_select_voice(
        self,
        character_name: str,
        character_description: str,
        voices: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """使用 LLM 选择最合适的音色"""
        
        system_prompt = """你是一位专业的配音导演，擅长根据角色特征选择最合适的音色。

你的任务是分析角色描述，从提供的音色列表中选择最匹配的音色。

请考虑以下因素：
1. 角色性别与音色性别匹配
2. 角色年龄与音色年龄特征匹配
3. 角色性格与音色特点匹配
4. 角色职业/身份与音色风格匹配

你必须以 JSON 格式返回结果，格式如下：
{
    "selected_voice_id": "选中的音色ID",
    "match_score": 85,
    "match_reason": "选择理由，说明为什么这个音色适合这个角色"
}

match_score 范围是 0-100，表示匹配度。
match_reason 请用中文简要说明选择理由。"""

        voice_prompt = self._build_voice_prompt(voices)
        
        user_prompt = f"""请为以下角色选择最合适的音色：

角色名称: {character_name}
角色描述: {character_description}

可选音色列表:
{voice_prompt}

请分析角色特征，选择最合适的音色，并返回 JSON 格式的结果。"""

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            
            response = await self._llm.ainvoke(messages)
            content = response.content
            
            # 提取 JSON
            import re
            json_match = re.search(r'\{[^}]*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
            else:
                # 尝试直接解析
                result = json.loads(content)
                return result
                
        except Exception as e:
            logger.error(f"[MatchVoice] LLM 选择音色失败: {e}")
            return None

    async def execute(
        self,
        state: ComicDramaState,
        character_description: str,
        character_name: str = "",
        gender: str = "unknown",
        exclude_voice_ids: Optional[List[str]] = None,
        limit: int = 5,
        **kwargs
    ) -> Dict[str, Any]:
        """
        根据描述匹配音色

        Args:
            state: 当前状态
            character_description: 角色描述
            character_name: 角色名称
            gender: 性别偏好
            exclude_voice_ids: 排除的音色ID
            limit: 返回数量限制

        Returns:
            匹配的音色列表
        """
        try:
            logger.info(f"[MatchVoice] 开始匹配: 角色={character_name}, 性别={gender}")
            logger.info(f"[MatchVoice] 描述: {character_description[:100] if character_description else '空'}...")
            
            # 加载精选音色
            result = self._load_tool.execute(
                state=state,
                voice_type="all",
                use_selected=True
            )

            if not result["success"]:
                logger.error(f"[MatchVoice] 加载音色失败: {result.get('error')}")
                return result

            voices = result["data"]["voices"]
            logger.info(f"[MatchVoice] 加载了 {len(voices)} 个音色")
            
            exclude_voice_ids = exclude_voice_ids or []
            logger.info(f"[MatchVoice] 排除的音色ID: {exclude_voice_ids}")
            
            # 过滤已使用的音色
            voices = [v for v in voices if v.get("id") not in exclude_voice_ids]
            logger.info(f"[MatchVoice] 排除后剩余 {len(voices)} 个音色")
            
            # 根据性别筛选（直接使用音色数据中的 gender 字段）
            original_voice_count = len(voices)
            if gender in ["male", "female"]:
                voices = [v for v in voices if v.get("gender") == gender]
            elif gender == "unknown":
                voices = [v for v in voices if v.get("gender") == "unknown"]
            
            logger.info(f"[MatchVoice] 性别筛选: {gender}, 从 {original_voice_count} 个筛选到 {len(voices)} 个")
            
            # 如果性别筛选后没有音色，使用所有音色（忽略性别）
            if not voices and original_voice_count > 0:
                logger.warning(f"[MatchVoice] 性别筛选后无音色，忽略性别使用所有音色")
                voices = result["data"]["voices"]
                voices = [v for v in voices if v.get("id") not in exclude_voice_ids]
            
            if not voices:
                logger.warning(f"[MatchVoice] 没有可用音色")
                return {
                    "success": True,
                    "message": "没有可用音色",
                    "data": {
                        "matched_voices": [],
                        "total_candidates": 0,
                        "search_params": {
                            "character_description": character_description,
                            "character_name": character_name,
                            "gender": gender
                        }
                    }
                }

            # 使用 LLM 选择音色
            logger.info(f"[MatchVoice] 使用 LLM 选择音色...")
            llm_result = await self._llm_select_voice(
                character_name=character_name,
                character_description=character_description,
                voices=voices
            )
            
            matched_voices = []
            
            if llm_result and llm_result.get("selected_voice_id"):
                selected_id = llm_result["selected_voice_id"]
                # 找到选中的音色
                for voice in voices:
                    if voice.get("id") == selected_id:
                        voice["match_score"] = llm_result.get("match_score", 80)
                        voice["match_reason"] = llm_result.get("match_reason", "LLM 推荐")
                        matched_voices.append(voice)
                        logger.info(f"[MatchVoice] LLM 选择音色: {voice.get('title')} (score: {voice['match_score']})")
                        break
            
            # 如果 LLM 没有选择成功，按使用次数排序推荐
            if not matched_voices:
                logger.info(f"[MatchVoice] LLM 未返回有效结果，按使用次数推荐")
                voices_sorted = sorted(voices, key=lambda v: v.get("task_count", 0), reverse=True)
                selected_voices = voices_sorted[:limit]
                for v in selected_voices:
                    v["match_score"] = 50
                    v["match_reason"] = f"根据性别({gender})推荐的热门音色"
                matched_voices = selected_voices
                if matched_voices:
                    logger.info(f"[MatchVoice] 推荐音色: {matched_voices[0].get('title')}")

            return {
                "success": True,
                "message": f"找到 {len(matched_voices)} 个匹配音色",
                "data": {
                    "matched_voices": matched_voices[:limit],
                    "total_candidates": len(matched_voices),
                    "search_params": {
                        "character_description": character_description,
                        "character_name": character_name,
                        "gender": gender
                    }
                }
            }

        except Exception as e:
            logger.error(f"[MatchVoice] 匹配音色失败: {e}", exc_info=True)
            return {
                "success": False,
                "message": "匹配音色失败",
                "error": str(e)
            }


class SelectVoiceForCharacterTool(BaseTool):
    """为角色选择音色工具"""

    name = "select_voice_for_character"
    description = """为单个角色选择最合适的 Fish Audio 音色。

输入参数：
- character_name: 角色名称
- character_description: 角色描述
- character_personality: 性格特点（可选）
- force_gender: 强制性别（可选）
- exclude_voice_ids: 排除的音色ID列表（避免重复，可选）
- allow_rematch: 是否允许重新匹配已有音色的角色（默认True）

功能：
1. 从 finalfish.json 加载精选音色
2. 根据角色描述智能匹配最佳音色
3. 支持排除已使用的音色
4. 返回选择的音色信息和选择理由

返回：
- voice_id: 选择的音色 ID
- voice_name: 音色名称
- voice_description: 音色描述
- match_score: 匹配度
- match_reason: 选择理由
"""

    def __init__(self, db_factory=None):
        super().__init__(db_factory)
        self._match_tool = MatchVoiceByDescriptionTool()

    def _extract_gender_from_description(self, description: str, name: str) -> str:
        """从描述和名称中提取性别"""
        text = (description + " " + name).lower()
        
        female_indicators = ["女", "她", "小姐", "女士", "妈妈", "姐姐", "妹妹", "老婆", "女友", "女神", "学姐", "female", "woman", "girl"]
        male_indicators = ["男", "他", "先生", "爸爸", "哥哥", "弟弟", "老公", "男友", "男神", "学长", "male", "man", "boy"]
        
        female_count = sum(1 for ind in female_indicators if ind in text)
        male_count = sum(1 for ind in male_indicators if ind in text)
        
        if female_count > male_count:
            return "female"
        elif male_count > female_count:
            return "male"
        return "unknown"

    async def execute(
        self,
        state: ComicDramaState,
        character_name: str,
        character_description: str,
        character_personality: Optional[str] = None,
        force_gender: Optional[str] = None,
        exclude_voice_ids: Optional[List[str]] = None,
        allow_rematch: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        为角色选择音色

        Args:
            state: 当前状态
            character_name: 角色名称
            character_description: 角色描述
            character_personality: 性格特点
            force_gender: 强制性别
            exclude_voice_ids: 排除的音色ID
            allow_rematch: 允许重新匹配

        Returns:
            选择的音色信息
        """
        try:
            # 确定性别
            gender = force_gender or self._extract_gender_from_description(
                character_description or "", character_name
            )
            
            logger.info(f"[SelectVoice] 角色: {character_name}, 推断性别: {gender}")
            logger.info(f"[SelectVoice] 描述: {character_description[:100] if character_description else '空'}...")
            logger.info(f"[SelectVoice] 性格: {character_personality[:100] if character_personality else '空'}...")
            
            # 合并描述和性格
            full_description = character_description or ""
            if character_personality:
                full_description += " " + character_personality
            
            # 匹配音色（异步调用）
            match_result = await self._match_tool.execute(
                state=state,
                character_description=full_description,
                character_name=character_name,
                gender=gender,
                exclude_voice_ids=exclude_voice_ids or [],
                limit=3
            )
            
            logger.info(f"[SelectVoice] 匹配结果: success={match_result.get('success')}, message={match_result.get('message', '无')}")
            
            if match_result.get('success') and match_result.get('data'):
                matched_voices = match_result['data'].get('matched_voices', [])
                logger.info(f"[SelectVoice] 匹配到 {len(matched_voices)} 个音色")
                if matched_voices:
                    for i, v in enumerate(matched_voices[:3]):
                        logger.info(f"[SelectVoice]   候选{i+1}: {v.get('title')} (score: {v.get('match_score')})")

            if not match_result["success"] or not match_result["data"]["matched_voices"]:
                logger.warning(f"[SelectVoice] 未找到适合角色 {character_name} 的音色，尝试放宽条件")
                
                # 第二次尝试：忽略 exclude_voice_ids，使用所有音色
                match_result = await self._match_tool.execute(
                    state=state,
                    character_description=full_description,
                    character_name=character_name,
                    gender="unknown",  # 忽略性别
                    exclude_voice_ids=[],  # 不排除任何音色
                    limit=3
                )
                
                if match_result.get('success') and match_result['data'].get('matched_voices'):
                    matched_voices = match_result['data']['matched_voices']
                    logger.info(f"[SelectVoice] 放宽条件后匹配到 {len(matched_voices)} 个音色")
                    best_match = matched_voices[0]
                    return {
                        "success": True,
                        "message": f"已为角色 {character_name} 选择音色（放宽条件）",
                        "data": {
                            "character_name": character_name,
                            "voice": {
                                "voice_id": best_match.get("id", ""),
                                "title": best_match.get("title", ""),
                                "description": best_match.get("description", ""),
                                "gender": best_match.get("gender", "unknown"),
                                "samples": best_match.get("samples", []),
                                "task_count": best_match.get("task_count", 0)
                            },
                            "match_score": best_match.get("match_score", 0),
                            "match_reason": best_match.get("match_reason", ""),
                            "selection_method": "relaxed_match"
                        }
                    }
                
                logger.error(f"[SelectVoice] 放宽条件后仍未找到适合角色 {character_name} 的音色")
                return {
                    "success": False,
                    "message": f"未找到适合角色 {character_name} 的音色",
                    "error": "no matching voice found"
                }

            best_match = match_result["data"]["matched_voices"][0]

            return {
                "success": True,
                "message": f"已为角色 {character_name} 选择最佳音色",
                "data": {
                    "character_name": character_name,
                    "voice": {
                        "voice_id": best_match.get("id", ""),
                        "title": best_match.get("title", ""),
                        "description": best_match.get("description", ""),
                        "gender": best_match.get("gender", "unknown"),
                        "samples": best_match.get("samples", []),
                        "task_count": best_match.get("task_count", 0)
                    },
                    "match_score": best_match.get("match_score", 0),
                    "match_reason": best_match.get("match_reason", ""),
                    "selection_method": "intelligent_match"
                }
            }

        except Exception as e:
            logger.error(f"为角色 {character_name} 选择音色失败: {e}")
            return {
                "success": False,
                "message": f"为角色 {character_name} 选择音色失败",
                "error": str(e)
            }


class BatchSelectVoiceTool(BaseTool):
    """批量选择音色工具"""

    name = "batch_select_voice"
    description = """批量为多个角色选择 Fish Audio 音色。

输入参数：
- character_names: 角色名称列表（可选，默认所有角色）
- skip_assigned: 是否跳过已有 voice_id 的角色（默认False，即重新匹配）
- force_rematch: 强制重新匹配所有角色（默认False）

功能：
1. 从状态中获取角色列表
2. 为每个角色选择音色
3. 自动避免音色重复分配给不同角色
4. 返回所有角色的选择结果

返回：
- success: 是否全部成功
- results: 各角色的选择结果
- summary: 统计摘要
- voice_assignments: 音色分配映射
"""

    def __init__(self, db_factory=None):
        super().__init__(db_factory)
        self._select_tool = SelectVoiceForCharacterTool()

    async def execute(
        self,
        state: ComicDramaState,
        character_names: Optional[List[str]] = None,
        skip_assigned: bool = False,
        force_rematch: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        批量选择音色

        Args:
            state: 当前状态
            character_names: 指定角色列表
            skip_assigned: 跳过已有音色的角色
            force_rematch: 强制重新匹配

        Returns:
            批量选择结果
        """
        try:
            characters = state.get("characters", [])

            if character_names:
                characters = [c for c in characters if c.get("name") in character_names]

            if not characters:
                return {
                    "success": False,
                    "message": "未找到需要选择音色的角色",
                    "error": "no characters found"
                }

            results = []
            used_voice_ids = set()
            voice_assignments = {}

            for character in characters:
                char_name = character.get("name", "")
                existing_voice_id = character.get("voice_id")
                
                logger.info(f"[BatchSelectVoice] 处理角色: {char_name}, 已有音色: {existing_voice_id}")

                # 如果跳过已分配且不是强制重新匹配
                if skip_assigned and existing_voice_id and not force_rematch:
                    logger.info(f"[BatchSelectVoice] 跳过角色 {char_name}（已有音色）")
                    results.append({
                        "character_name": char_name,
                        "status": "skipped",
                        "reason": "已有音色",
                        "voice_id": existing_voice_id
                    })
                    used_voice_ids.add(existing_voice_id)
                    voice_assignments[char_name] = existing_voice_id
                    continue

                # 选择音色 - 支持多种字段名
                character_description = (
                    character.get("description") or 
                    character.get("basic_info") or 
                    ""
                )
                character_personality = (
                    character.get("personality") or 
                    character.get("appearance") or 
                    ""
                )
                
                logger.info(f"[BatchSelectVoice] 角色 {char_name} 描述: {character_description[:50] if character_description else '空'}...")
                logger.info(f"[BatchSelectVoice] 角色 {char_name} 性格: {character_personality[:50] if character_personality else '空'}...")
                
                result = await self._select_tool.execute(
                    state=state,
                    character_name=char_name,
                    character_description=character_description,
                    character_personality=character_personality,
                    exclude_voice_ids=list(used_voice_ids),
                    allow_rematch=force_rematch or not skip_assigned
                )
                
                logger.info(f"[BatchSelectVoice] 角色 {char_name} 选择结果: success={result.get('success')}, error={result.get('error', '无')}")

                if result["success"]:
                    voice_id = result["data"]["voice"]["voice_id"]
                    used_voice_ids.add(voice_id)
                    voice_assignments[char_name] = voice_id
                    
                    results.append({
                        "character_name": char_name,
                        "status": "success",
                        "voice_id": voice_id,
                        "voice_title": result["data"]["voice"]["title"],
                        "match_score": result["data"]["match_score"],
                        "match_reason": result["data"]["match_reason"],
                        "is_rematch": existing_voice_id is not None
                    })
                else:
                    results.append({
                        "character_name": char_name,
                        "status": "failed",
                        "error": result.get("error", "unknown error"),
                        "existing_voice_id": existing_voice_id
                    })

            success_count = sum(1 for r in results if r["status"] == "success")
            failed_count = sum(1 for r in results if r["status"] == "failed")
            skipped_count = sum(1 for r in results if r["status"] == "skipped")
            rematch_count = sum(1 for r in results if r.get("is_rematch"))

            return {
                "success": failed_count == 0,
                "message": f"批量选择音色完成：成功 {success_count}，失败 {failed_count}，跳过 {skipped_count}",
                "data": {
                    "results": results,
                    "summary": {
                        "total": len(results),
                        "success": success_count,
                        "failed": failed_count,
                        "skipped": skipped_count,
                        "rematched": rematch_count
                    },
                    "voice_assignments": voice_assignments
                }
            }

        except Exception as e:
            logger.error(f"[BatchSelectVoice] 批量选择音色失败: {e}", exc_info=True)
            return {
                "success": False,
                "message": "批量选择音色失败",
                "error": str(e)
            }


class RematchVoiceTool(BaseTool):
    """重新匹配音色工具"""

    name = "rematch_voice"
    description = """为角色重新匹配音色。

输入参数：
- character_name: 角色名称（指定单个角色）
- rematch_all: 是否重新匹配所有角色（默认False）
- keep_current: 是否保留当前音色作为备选（默认False）

功能：
1. 重新为指定角色或所有角色匹配音色
2. 确保新音色与当前音色不同
3. 返回新的匹配结果

返回：
- 单个角色的新音色信息，或所有角色的重新匹配结果
"""

    def __init__(self, db_factory=None):
        super().__init__(db_factory)
        self._select_tool = SelectVoiceForCharacterTool()
        self._batch_tool = BatchSelectVoiceTool()

    def execute(
        self,
        state: ComicDramaState,
        character_name: Optional[str] = None,
        rematch_all: bool = False,
        keep_current: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        重新匹配音色

        Args:
            state: 当前状态
            character_name: 指定角色名称
            rematch_all: 重新匹配所有
            keep_current: 保留当前音色

        Returns:
            重新匹配结果
        """
        try:
            if rematch_all:
                # 重新匹配所有角色
                return self._batch_tool.execute(
                    state=state,
                    skip_assigned=False,
                    force_rematch=True
                )
            
            elif character_name:
                # 重新匹配单个角色
                characters = state.get("characters", [])
                character = None
                for c in characters:
                    if c.get("name") == character_name:
                        character = c
                        break
                
                if not character:
                    return {
                        "success": False,
                        "message": f"未找到角色: {character_name}",
                        "error": "character not found"
                    }
                
                # 获取其他角色已使用的音色
                other_voices = set()
                for c in characters:
                    if c.get("name") != character_name and c.get("voice_id"):
                        other_voices.add(c.get("voice_id"))
                
                # 如果不保留当前音色，也加入排除列表
                current_voice_id = character.get("voice_id")
                exclude_ids = list(other_voices)
                if current_voice_id and not keep_current:
                    exclude_ids.append(current_voice_id)
                
                # 重新选择
                result = self._select_tool.execute(
                    state=state,
                    character_name=character_name,
                    character_description=character.get("description", ""),
                    character_personality=character.get("personality", ""),
                    exclude_voice_ids=exclude_ids,
                    allow_rematch=True
                )
                
                if result["success"]:
                    return {
                        "success": True,
                        "message": f"已为角色 {character_name} 重新匹配音色",
                        "data": {
                            "character_name": character_name,
                            "previous_voice_id": current_voice_id,
                            "new_voice": result["data"]["voice"],
                            "match_score": result["data"]["match_score"],
                            "match_reason": result["data"]["match_reason"]
                        }
                    }
                else:
                    return result
            
            else:
                return {
                    "success": False,
                    "message": "请指定 character_name 或设置 rematch_all=True",
                    "error": "missing parameters"
                }

        except Exception as e:
            logger.error(f"重新匹配音色失败: {e}")
            return {
                "success": False,
                "message": "重新匹配音色失败",
                "error": str(e)
            }
