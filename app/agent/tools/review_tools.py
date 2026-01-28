"""
审核工具 - Review Tools

提供人工审核和自动审核功能
"""

from typing import Dict, Any, List, Optional
from app.agent.tools.base import BaseTool
from app.agent.state.schemas import ComicDramaState
from app.core.logger import logger


class ReviewCharacterTool(BaseTool):
    """审核角色工具"""
    
    name = "review_character"
    description = "审核角色图片和质量"
    
    async def execute(
        self,
        state: ComicDramaState,
        character_name: str,
        review_notes: Optional[str] = None,
        approved: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        审核角色
        
        Args:
            character_name: 角色名称
            review_notes: 审核备注
            approved: 是否通过
        """
        characters = state.get("characters", [])
        
        for char in characters:
            if char.get("name") == character_name:
                char["review_status"] = "approved" if approved else "rejected"
                char["review_notes"] = review_notes
                char["reviewed_at"] = ""
                
                logger.info(f"角色 {character_name} 审核: {'通过' if approved else '拒绝'}")
                
                return {
                    "success": True,
                    "character_name": character_name,
                    "approved": approved,
                    "review_notes": review_notes
                }
        
        return {
            "success": False,
            "error": f"角色不存在: {character_name}"
        }


class ReviewSceneTool(BaseTool):
    """审核场景工具"""
    
    name = "review_scene"
    description = "审核场景图片和质量"
    
    async def execute(
        self,
        state: ComicDramaState,
        scene_name: str,
        review_notes: Optional[str] = None,
        approved: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """审核场景"""
        scenes = state.get("scenes", [])
        
        for scene in scenes:
            if scene.get("name") == scene_name:
                scene["review_status"] = "approved" if approved else "rejected"
                scene["review_notes"] = review_notes
                scene["reviewed_at"] = ""
                
                logger.info(f"场景 {scene_name} 审核: {'通过' if approved else '拒绝'}")
                
                return {
                    "success": True,
                    "scene_name": scene_name,
                    "approved": approved,
                    "review_notes": review_notes
                }
        
        return {
            "success": False,
            "error": f"场景不存在: {scene_name}"
        }


class ReviewStoryboardTool(BaseTool):
    """审核分镜工具"""
    
    name = "review_storyboard"
    description = "审核分镜脚本和质量"
    
    async def execute(
        self,
        state: ComicDramaState,
        storyboard_id: str,
        review_notes: Optional[str] = None,
        approved: bool = True,
        modifications: Optional[List[Dict]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        审核分镜
        
        Args:
            storyboard_id: 分镜 ID
            review_notes: 审核备注
            approved: 是否通过
            modifications: 修改建议列表
        """
        storyboards = state.get("storyboards", [])
        
        for sb in storyboards:
            if sb.get("id") == storyboard_id:
                sb["review_status"] = "approved" if approved else "rejected"
                sb["review_notes"] = review_notes
                sb["modifications"] = modifications or []
                sb["reviewed_at"] = ""
                
                logger.info(f"分镜 {storyboard_id} 审核: {'通过' if approved else '拒绝'}")
                
                return {
                    "success": True,
                    "storyboard_id": storyboard_id,
                    "approved": approved,
                    "review_notes": review_notes,
                    "modifications": modifications
                }
        
        return {
            "success": False,
            "error": f"分镜不存在: {storyboard_id}"
        }


class ReviewVideoSegmentTool(BaseTool):
    """审核视频片段工具"""
    
    name = "review_video_segment"
    description = "审核生成的视频片段"
    
    async def execute(
        self,
        state: ComicDramaState,
        video_id: str,
        review_notes: Optional[str] = None,
        approved: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """审核视频片段"""
        video_segments = state.get("video_segments", [])
        
        for video in video_segments:
            if video.get("id") == video_id:
                video["review_status"] = "approved" if approved else "rejected"
                video["review_notes"] = review_notes
                video["reviewed_at"] = ""
                
                logger.info(f"视频 {video_id} 审核: {'通过' if approved else '拒绝'}")
                
                return {
                    "success": True,
                    "video_id": video_id,
                    "approved": approved,
                    "review_notes": review_notes
                }
        
        return {
            "success": False,
            "error": f"视频不存在: {video_id}"
        }


class BatchReviewTool(BaseTool):
    """批量审核工具"""
    
    name = "batch_review"
    description = "批量审核多个资产"
    
    async def execute(
        self,
        state: ComicDramaState,
        asset_type: str,
        reviews: List[Dict[str, Any]],
        **kwargs
    ) -> Dict[str, Any]:
        """
        批量审核
        
        Args:
            asset_type: 资产类型（character/scene/storyboard/video）
            reviews: 审核列表，包含 id, approved, notes
        """
        results = []
        approved_count = 0
        rejected_count = 0
        
        for review in reviews:
            asset_id = review.get("id")
            approved = review.get("approved", True)
            notes = review.get("notes")
            
            if asset_type == "character":
                result = await ReviewCharacterTool().execute(
                    state, asset_id, notes, approved
                )
            elif asset_type == "scene":
                result = await ReviewSceneTool().execute(
                    state, asset_id, notes, approved
                )
            elif asset_type == "storyboard":
                result = await ReviewStoryboardTool().execute(
                    state, asset_id, notes, approved
                )
            elif asset_type == "video":
                result = await ReviewVideoSegmentTool().execute(
                    state, asset_id, notes, approved
                )
            else:
                result = {"success": False, "error": f"不支持的资产类型: {asset_type}"}
            
            if result.get("success"):
                results.append(result)
                if approved:
                    approved_count += 1
                else:
                    rejected_count += 1
        
        logger.info(f"批量审核完成: 通过 {approved_count}, 拒绝 {rejected_count}")
        
        return {
            "success": True,
            "asset_type": asset_type,
            "total": len(reviews),
            "approved": approved_count,
            "rejected": rejected_count,
            "results": results
        }


class QualityCheckTool(BaseTool):
    """质量检查工具"""
    
    name = "quality_check"
    description = "自动检查生成内容的质量"
    
    async def execute(
        self,
        state: ComicDramaState,
        asset_type: str,
        asset_id: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        质量检查
        
        Args:
            asset_type: 资产类型
            asset_id: 资产 ID
        """
        from app.utils.ai_client import AIClient
        
        try:
            ai_client = AIClient()
            
            if asset_type == "character":
                asset = next(
                    (c for c in state.get("characters", []) if c.get("name") == asset_id),
                    None
                )
                if not asset:
                    return {"success": False, "error": f"角色不存在: {asset_id}"}
                
                description = asset.get("description", "")
                image_url = asset.get("image_url", "")
                
                prompt = f"""请检查角色图片和描述是否匹配。

角色名称: {asset.get('name', '')}
角色描述: {description}
图片URL: {image_url}

请输出 JSON:
{{
    "match_score": 0-100,
    "issues": ["问题列表"],
    "suggestions": ["改进建议"],
    "overall_quality": "优秀/良好/一般/差"
}}"""
            
            elif asset_type == "scene":
                asset = next(
                    (s for s in state.get("scenes", []) if s.get("name") == asset_id),
                    None
                )
                if not asset:
                    return {"success": False, "error": f"场景不存在: {asset_id}"}
                
                prompt = f"""请检查场景图片和描述是否匹配。

场景名称: {asset.get('name', '')}
场景描述: {asset.get('description', '')}
图片URL: {asset.get('image_url', '')}

请输出 JSON:
{{
    "match_score": 0-100,
    "issues": ["问题列表"],
    "suggestions": ["改进建议"],
    "overall_quality": "优秀/良好/一般/差"
}}"""
            
            else:
                return {"success": False, "error": f"不支持的资产类型: {asset_type}"}
            
            result = await ai_client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model="Qwen/Qwen-Plus"
            )
            
            import json
            try:
                content = result.get("content", "")
                json_match = content.find("{")
                quality_result = json.loads(content[json_match:]) if json_match >= 0 else {}
                
                return {
                    "success": True,
                    "asset_type": asset_type,
                    "asset_id": asset_id,
                    "quality_result": quality_result
                }
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "asset_type": asset_type,
                    "asset_id": asset_id,
                    "raw_result": result.get("content")
                }
                
        except Exception as e:
            logger.error(f"质量检查失败: {e}")
            return {"success": False, "error": str(e)}
