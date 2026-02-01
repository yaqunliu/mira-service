"""
音色选择 Agent 的 LangGraph 节点定义

提供音色选择工作流的各个节点
"""

from typing import Dict, Any, Optional
from app.agent.state.schemas import ComicDramaState
from app.agent.agents.voice_selection_agent import VoiceSelectionAgent
from app.core.logger import logger


voice_selection_agent = None


def get_voice_selection_agent() -> VoiceSelectionAgent:
    """获取音色选择 Agent 单例"""
    global voice_selection_agent
    if voice_selection_agent is None:
        voice_selection_agent = VoiceSelectionAgent()
    return voice_selection_agent


def load_voice_list_node(state: ComicDramaState) -> ComicDramaState:
    """
    加载可用音色列表节点

    Args:
        state: 当前状态

    Returns:
        更新后的状态
    """
    logger.info("执行节点: load_voice_list")

    try:
        agent = get_voice_selection_agent()
        result = agent.get_available_voices(state)

        if result["success"]:
            state["voice_list"] = result["data"]
            logger.info(f"已加载 {result['data']['statistics']['total']} 个音色")
        else:
            logger.warning(f"加载音色列表失败: {result.get('error')}")
            state["errors"] = state.get("errors", []) + [{
                "node": "load_voice_list",
                "error": result.get("error", "unknown")
            }]

    except Exception as e:
        logger.error(f"加载音色列表节点执行失败: {e}")
        state["errors"] = state.get("errors", []) + [{
            "node": "load_voice_list",
            "error": str(e)
        }]

    return state


def select_voice_for_character_node(
    state: ComicDramaState,
    character_name: str,
    force_gender: Optional[str] = None
) -> ComicDramaState:
    """
    为单个角色选择音色节点

    Args:
        state: 当前状态
        character_name: 角色名称
        force_gender: 强制性别

    Returns:
        更新后的状态
    """
    logger.info(f"执行节点: select_voice_for_character - {character_name}")

    try:
        agent = get_voice_selection_agent()

        character = None
        for c in state.get("characters", []):
            if c.get("name") == character_name:
                character = c
                break

        if not character:
            logger.warning(f"未找到角色: {character_name}")
            return state

        result = agent.select_voice_for_character(
            state=state,
            character_name=character_name,
            character_description=character.get("description"),
            character_personality=character.get("personality"),
            force_gender=force_gender
        )

        if result["success"]:
            voice_data = result["data"]
            for c in state.get("characters", []):
                if c.get("name") == character_name:
                    c["voice_id"] = voice_data["voice"]["voice_id"]
                    c["voice_name"] = voice_data["voice"]["title"]
                    c["voice_match_score"] = voice_data.get("match_score")
                    c["voice_match_reasons"] = voice_data.get("match_reasons", [])
                    logger.info(f"角色 {character_name} 已分配音色: {voice_data['voice']['title']}")
                    break
        else:
            logger.warning(f"为角色 {character_name} 选择音色失败: {result.get('error')}")

    except Exception as e:
        logger.error(f"为角色 {character_name} 选择音色节点执行失败: {e}")
        state["errors"] = state.get("errors", []) + [{
            "node": f"select_voice_for_{character_name}",
            "error": str(e)
        }]

    return state


def batch_select_voice_node(
    state: ComicDramaState,
    character_names: Optional[list] = None,
    skip_named: bool = True
) -> ComicDramaState:
    """
    批量选择音色节点

    Args:
        state: 当前状态
        character_names: 指定角色列表（None 表示所有角色）
        skip_named: 是否跳过已有音色的角色

    Returns:
        更新后的状态
    """
    logger.info("执行节点: batch_select_voice")

    try:
        agent = get_voice_selection_agent()

        result = agent.select_voice_for_all_characters(
            state=state,
            character_names=character_names,
            skip_named_voices=skip_named
        )

        if result["success"]:
            state["voice_selection_summary"] = result["data"]["summary"]
            logger.info(f"批量选择音色完成: {result['message']}")

            for r in result["data"]["results"]:
                if r["status"] == "success":
                    for c in state.get("characters", []):
                        if c.get("name") == r["character_name"]:
                            c["voice_id"] = r["voice"]["voice_id"]
                            c["voice_name"] = r["voice"]["title"]
                            c["voice_match_score"] = r.get("match_score")
                            break
        else:
            logger.warning(f"批量选择音色失败: {result.get('error')}")
            state["errors"] = state.get("errors", []) + [{
                "node": "batch_select_voice",
                "error": result.get("error")
            }]

    except Exception as e:
        logger.error(f"批量选择音色节点执行失败: {e}")
        state["errors"] = state.get("errors", []) + [{
            "node": "batch_select_voice",
            "error": str(e)
        }]

    return state


def analyze_character_voice_needs_node(
    state: ComicDramaState,
    character_name: str
) -> ComicDramaState:
    """
    分析角色音色需求节点

    Args:
        state: 当前状态
        character_name: 角色名称

    Returns:
        更新后的状态
    """
    logger.info(f"执行节点: analyze_character_voice_needs - {character_name}")

    try:
        agent = get_voice_selection_agent()

        dialogues = []
        for shot in state.get("storyboards", []):
            for dialogue in shot.get("dialogues", []):
                if dialogue.get("character_name") == character_name:
                    dialogues.append(dialogue.get("text", ""))

        result = agent.analyze_character_voice_needs(
            state=state,
            character_name=character_name,
            dialogues=dialogues if dialogues else None
        )

        if result["success"]:
            voice_needs = result["data"]
            for c in state.get("characters", []):
                if c.get("name") == character_name:
                    c["voice_needs_analysis"] = voice_needs
                    logger.info(f"角色 {character_name} 音色需求分析完成")
                    break
        else:
            logger.warning(f"分析角色 {character_name} 音色需求失败")

    except Exception as e:
        logger.error(f"分析角色 {character_name} 音色需求节点执行失败: {e}")
        state["errors"] = state.get("errors", []) + [{
            "node": f"analyze_voice_needs_{character_name}",
            "error": str(e)
        }]

    return state


def update_character_voice_node(
    state: ComicDramaState,
    character_name: str,
    voice_id: str,
    voice_speed: Optional[str] = None
) -> ComicDramaState:
    """
    更新角色音色节点

    Args:
        state: 当前状态
        character_name: 角色名称
        voice_id: 音色 ID
        voice_speed: 语速

    Returns:
        更新后的状态
    """
    logger.info(f"执行节点: update_character_voice - {character_name}")

    try:
        agent = get_voice_selection_agent()

        result = agent.update_character_voice(
            state=state,
            character_name=character_name,
            voice_id=voice_id,
            voice_speed=voice_speed
        )

        if result["success"]:
            logger.info(f"已更新角色 {character_name} 的音色为 {voice_id}")
        else:
            logger.warning(f"更新角色 {character_name} 音色失败: {result.get('error')}")
            state["errors"] = state.get("errors", []) + [{
                "node": "update_character_voice",
                "error": result.get("error")
            }]

    except Exception as e:
        logger.error(f"更新角色 {character_name} 音色节点执行失败: {e}")
        state["errors"] = state.get("errors", []) + [{
            "node": "update_character_voice",
            "error": str(e)
        }]

    return state


def should_select_voice(state: ComicDramaState) -> str:
    """
    判断是否需要选择音色的路由函数

    Args:
        state: 当前状态

    Returns:
        下一节点名称
    """
    characters = state.get("characters", [])
    characters_needing_voice = [
        c for c in characters if not c.get("voice_id")
    ]

    if not characters_needing_voice:
        logger.info("所有角色已有音色，跳过音色选择")
        return "skip_voice_selection"

    if len(characters_needing_voice) <= 2:
        return "select_individual_voices"

    return "batch_select_voice"


def voice_selection_completed_condition(state: ComicDramaState) -> str:
    """
    音色选择完成条件判断

    Args:
        state: 当前状态

    Returns:
        下一节点名称
    """
    characters = state.get("characters", [])
    characters_needing_voice = [
        c for c in characters if not c.get("voice_id")
    ]

    if not characters_needing_voice:
        return "voice_selection_completed"

    if state.get("errors") and len(state["errors"]) > 3:
        return "voice_selection_failed"

    return "continue_selection"


VOICE_SELECTION_NODES = {
    "load_voice_list": load_voice_list_node,
    "batch_select_voice": batch_select_voice_node,
    "select_voice_for_character": select_voice_for_character_node,
    "analyze_character_voice_needs": analyze_character_voice_needs_node,
    "update_character_voice": update_character_voice_node,
}


VOICE_SELECTION_EDGES = [
    ("load_voice_list", "should_select_voice"),
    ("should_select_voice", "batch_select_voice"),
    ("should_select_voice", "select_individual_voice"),
    ("should_select_voice", "skip_voice_selection"),
    ("batch_select_voice", "voice_selection_completed_condition"),
    ("select_individual_voice", "voice_selection_completed_condition"),
]


VOICE_SELECTION_CONDITIONAL_EDGES = {
    "should_select_voice": {
        "batch_select_voice": lambda s: s.get("__next_node") == "batch_select_voice",
        "select_individual_voice": lambda s: s.get("__next_node") == "select_individual_voice",
        "skip_voice_selection": lambda s: s.get("__next_node") == "skip_voice_selection",
    },
    "voice_selection_completed_condition": {
        "voice_selection_completed": lambda s: True,
        "continue_selection": lambda s: False,
        "voice_selection_failed": lambda s: False,
    },
}
