"""
Human Review 节点

处理需要人工确认的检查点，支持 approve/reject/modify 操作
"""

from typing import Dict, Any, List, Optional

from app.core.logger import logger


async def human_review_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Human Review 节点
    
    当工作流到达需要人工确认的检查点时：
    1. 准备待审核数据
    2. 生成确认消息和选项
    3. 等待用户响应
    
    Args:
        state: 当前 Graph 状态
        
    Returns:
        更新后的状态，包含 pending_approval=True
    """
    logger.info("[Node] human_review: 进入人工确认节点")
    
    from datetime import datetime
    
    checkpoint_data = state.get("checkpoint_data", {})
    checkpoint_type = checkpoint_data.get("checkpoint_type", "unknown")
    
    # 如果上一个节点已经设置了完整的响应消息，则不再生成重复消息
    existing_response = state.get("response_text", "")
    already_pending = state.get("pending_approval", False)
    
    if existing_response and already_pending:
        logger.info(f"[Node] human_review: 上一节点已设置响应，跳过消息生成")
        # 保持现有状态，只确保 pending_approval 为 True
        return {
            "pending_approval": True,
            "updated_at": datetime.now().isoformat(),
        }
    
    try:
        # 根据检查点类型生成确认消息
        message, options = _generate_review_message(checkpoint_type, checkpoint_data)
        
        # 构建 Human Review 消息
        review_message = {
            "role": "assistant",
            "content": message,
            "timestamp": datetime.now().isoformat(),
            "node": "human_review",
            "metadata": {
                "checkpoint_type": checkpoint_type,
                "requires_action": True,
                "available_actions": options,
            },
        }
        
        # 构建看板操作（高亮待审核内容）
        board_actions = _generate_board_actions(checkpoint_type, checkpoint_data)
        
        messages = list(state.get("messages", []))
        messages.append(review_message)
        
        logger.info(f"[Node] human_review: 等待用户确认，type={checkpoint_type}")
        
        return {
            "messages": messages,
            "response_text": message,
            "pending_approval": True,
            "checkpoint_data": checkpoint_data,
            "board_actions": board_actions,
            "updated_at": datetime.now().isoformat(),
        }
        
    except Exception as e:
        logger.error(f"[Node] human_review 错误: {e}")
        
        return {
            "messages": state.get("messages", []) + [{
                "role": "assistant",
                "content": f"准备审核数据时出现错误：{str(e)}",
                "timestamp": datetime.now().isoformat(),
                "node": "human_review",
                "error": True,
            }],
            "errors": state.get("errors", []) + [{"node": "human_review", "error": str(e)}],
        }


def _generate_review_message(
    checkpoint_type: str,
    checkpoint_data: Dict[str, Any]
) -> tuple:
    """生成审核消息和选项"""
    
    if checkpoint_type == "script_analysis":
        data = checkpoint_data.get("data", {})
        characters = data.get("characters", [])
        scenes = data.get("scenes", [])
        
        message = f"""📋 **剧本分析完成，请确认：**

**识别到的角色** ({len(characters)} 个)：
{_format_list([c.get('name') for c in characters[:5]])}
{"..." if len(characters) > 5 else ""}

**识别到的场景** ({len(scenes)} 个)：
{_format_list([s.get('name') for s in scenes[:5]])}
{"..." if len(scenes) > 5 else ""}

请选择：
- 回复「确认」继续生成
- 回复「修改」调整内容
- 回复「取消」放弃本次分析"""

        options = ["approve", "modify", "reject"]
        
    elif checkpoint_type == "asset_finalization":
        data = checkpoint_data.get("data", {})
        
        message = f"""🎨 **资产生成完成，请确认：**

角色图片：{data.get('characters_completed', 0)}/{data.get('characters_total', 0)}
场景图片：{data.get('scenes_completed', 0)}/{data.get('scenes_total', 0)}

请在右侧看板中查看生成结果，然后：
- 回复「确认」继续下一步
- 点击具体资产进行修改"""

        options = ["approve", "modify"]
        
    elif checkpoint_type == "storyboard_batch":
        data = checkpoint_data.get("data", {})
        batch_number = data.get("batch_number", 1)
        total_batches = data.get("total_batches", 1)
        
        message = f"""🎬 **分镜批次 {batch_number}/{total_batches} 已生成：**

本批次完成 {data.get('batch_size', 0)} 个分镜。

请检查分镜内容：
- 回复「确认」继续生成下一批
- 回复「修改」调整本批次分镜"""

        options = ["approve", "modify"]
        
    elif checkpoint_type == "final_review":
        message = """✅ **创作完成，最终确认：**

所有内容已生成完毕，请进行最终检查：
- 回复「确认」开始合成最终视频
- 回复「修改」返回调整"""

        options = ["approve", "modify"]
        
    else:
        message = f"""⚠️ **需要确认：**

{checkpoint_data.get('message', '请确认是否继续？')}

- 回复「确认」继续
- 回复「取消」放弃"""

        options = ["approve", "reject"]
    
    return message, options


def _format_list(items: List[str]) -> str:
    """格式化列表"""
    if not items:
        return "（无）"
    return "\n".join([f"  • {item}" for item in items if item])


def _generate_board_actions(
    checkpoint_type: str,
    checkpoint_data: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """生成看板操作"""
    actions = []
    
    if checkpoint_type == "script_analysis":
        # 刷新角色和场景列表
        actions.append({
            "action": "refresh",
            "target": "characters",
            "data": {},
        })
        actions.append({
            "action": "refresh",
            "target": "scenes",
            "data": {},
        })
        
    elif checkpoint_type == "asset_finalization":
        # 高亮待确认的资产
        actions.append({
            "action": "highlight",
            "target": "assets",
            "data": {"status": "pending_review"},
        })
        
    elif checkpoint_type == "storyboard_batch":
        # 滚动到新生成的分镜
        data = checkpoint_data.get("data", {})
        first_shot_id = data.get("first_shot_id")
        if first_shot_id:
            actions.append({
                "action": "scroll",
                "target": f"shot_{first_shot_id}",
                "data": {},
            })
    
    return actions


def process_user_feedback(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理用户反馈（辅助函数）
    
    根据 user_feedback 更新状态，决定下一步流程
    """
    user_feedback = state.get("user_feedback", {})
    action = user_feedback.get("action", "")
    
    if action == "approve":
        return {
            "pending_approval": False,
            "user_feedback": None,
            "next_action": "continue",
        }
    elif action == "reject":
        return {
            "pending_approval": False,
            "user_feedback": None,
            "next_action": "abort",
        }
    elif action == "modify":
        modifications = user_feedback.get("modifications", {})
        return {
            "pending_approval": False,
            "user_feedback": None,
            "pending_modifications": modifications,
            "next_action": "modify",
        }
    
    return {"pending_approval": True}
