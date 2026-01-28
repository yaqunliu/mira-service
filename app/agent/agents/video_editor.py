"""
剪辑师 - Video Editor Agent

负责最终的视频剪辑和合成
"""

from typing import Dict, Any, List, Optional
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from app.agent.state.schemas import ComicDramaState
from app.agent.tools.editing_tools import (
    ConcatenateVideoTool,
    AddAudioTrackTool,
    AddSubtitleTool,
    ApplyTransitionTool,
    FinalRenderTool
)
from app.agent.tools.review_tools import ReviewVideoSegmentTool
from app.core.logger import logger
from app.core.config import settings
import json


class VideoEditor:
    """剪辑师 Agent"""
    
    def __init__(self):
        """初始化剪辑师"""
        self.llm = ChatOpenAI(
            model=settings.LLM_MODEL_SCRIPT_GENERATION,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.2
        )
        self.concatenate_tool = ConcatenateVideoTool()
        self.add_audio_tool = AddAudioTrackTool()
        self.add_subtitle_tool = AddSubtitleTool()
        self.apply_transition_tool = ApplyTransitionTool()
        self.final_render_tool = FinalRenderTool()
        self.review_tool = ReviewVideoSegmentTool()
        logger.info("剪辑师初始化完成")
    
    async def create_editing_plan(
        self,
        state: ComicDramaState
    ) -> Dict[str, Any]:
        """
        创建剪辑计划
        
        Args:
            state: 当前状态
            
        Returns:
            剪辑计划
        """
        storyboards = state.get("storyboards", [])
        audio_segments = state.get("audio_segments", [])
        
        if not storyboards:
            return {"success": False, "error": "没有分镜数据", "plan": []}
        
        try:
            system_prompt = """请根据分镜和音频创建详细的剪辑计划。

输出格式：
{
    "editing_plan": [
        {
            "sequence": 1,
            "storyboard_id": "分镜ID",
            "video_segment_id": "视频片段ID",
            "audio_overlay": [
                {
                    "type": "voiceover/bgm/sfx",
                    "audio_id": "音频ID",
                    "start_time": 0,
                    "volume": 0.8
                }
            ],
            "transitions": {
                "from_previous": "转场类型",
                "to_next": "转场类型",
                "duration": 1.0
            },
            "subtitles": [
                {
                    "start_time": 0,
                    "end_time": 5,
                    "text": "字幕内容"
                }
            ]
        }
    ],
    "total_duration": "总时长",
    "notes": "剪辑备注"
}"""

            context = f"""
分镜数据：
{json.dumps(storyboards, ensure_ascii=False, indent=2)}

音频数据：
{json.dumps(audio_segments, ensure_ascii=False, indent=2)}
"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=context)
            ]
            
            response = await self.llm.ainvoke(messages)
            content = response.content
            
            # 解析 JSON
            import re
            json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content
            
            result = json.loads(json_str)
            
            return {
                "success": True,
                "editing_plan": result.get("editing_plan", []),
                "total_duration": result.get("total_duration", ""),
                "notes": result.get("notes", "")
            }
            
        except Exception as e:
            logger.error(f"创建剪辑计划失败: {e}")
            return {"success": False, "error": str(e), "plan": []}
    
    async def assemble_video(
        self,
        state: ComicDramaState,
        editing_plan: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        组装视频
        
        Args:
            state: 当前状态
            editing_plan: 剪辑计划
            
        Returns:
            组装结果
        """
        video_segments = state.get("video_segments", [])
        approved_videos = [
            v for v in video_segments
            if v.get("review_status") == "approved"
        ]
        
        if not approved_videos and not editing_plan:
            return {"success": False, "error": "没有已审核的视频片段"}
        
        try:
            if not editing_plan:
                plan_result = await self.create_editing_plan(state)
                if not plan_result["success"]:
                    return plan_result
                editing_plan = plan_result.get("editing_plan", [])
            
            video_ids = [v.get("id") for v in approved_videos]
            
            concat_result = await self.concatenate_tool.execute(
                state=state,
                video_ids=video_ids,
                output_filename="assembled.mp4"
            )
            
            if not concat_result.get("success"):
                return concat_result
            
            assembled_video = {
                "id": "assembled_video",
                "video_url": concat_result.get("output_url"),
                "duration": concat_result.get("duration"),
                "segments": video_ids,
                "status": "assembled"
            }
            
            if "assembled_videos" not in state:
                state["assembled_videos"] = []
            
            state["assembled_videos"].append(assembled_video)
            
            logger.info(f"视频组装完成: {len(video_ids)} 个片段")
            
            return {
                "success": True,
                "assembled_video": assembled_video,
                "segment_count": len(video_ids)
            }
            
        except Exception as e:
            logger.error(f"视频组装失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def add_music_and_sfx(
        self,
        state: ComicDramaState,
        video_id: str,
        bgm_url: Optional[str] = None,
        sfx_list: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        添加背景音乐和音效
        
        Args:
            state: 当前状态
            video_id: 视频 ID
            bgm_url: 背景音乐 URL
            sfx_list: 音效列表
            
        Returns:
            添加结果
        """
        results = []
        
        if bgm_url:
            bgm_result = await self.add_audio_tool.execute(
                state=state,
                video_id=video_id,
                audio_type="bgm",
                audio_url=bgm_url,
                volume=0.5,
                fade_in=2.0,
                fade_out=2.0
            )
            results.append(bgm_result)
        
        if sfx_list:
            for sfx in sfx_list:
                sfx_result = await self.add_audio_tool.execute(
                    state=state,
                    video_id=video_id,
                    audio_type="sound_effect",
                    audio_url=sfx.get("url"),
                    volume=sfx.get("volume", 0.8)
                )
                results.append(sfx_result)
        
        success_count = sum(1 for r in results if r.get("success"))
        
        return {
            "success": success_count == len(results),
            "video_id": video_id,
            "audio_tracks_added": success_count
        }
    
    async def add_subtitles_to_video(
        self,
        state: ComicDramaState,
        video_id: str,
        subtitles: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """
        添加字幕到视频
        
        Args:
            state: 当前状态
            video_id: 视频 ID
            subtitles: 字幕列表
            
        Returns:
            添加结果
        """
        if not subtitles:
            audio_segments = state.get("audio_segments", [])
            subtitles = []
            
            for audio in audio_segments:
                if audio.get("text") and audio.get("duration"):
                    subtitles.append({
                        "start_time": audio.get("start_time", 0),
                        "end_time": (audio.get("start_time", 0) + 
                                    audio.get("duration", 5)),
                        "text": audio.get("text", "")
                    })
        
        if not subtitles:
            return {"success": False, "error": "没有字幕数据"}
        
        result = await self.add_subtitle_tool.execute(
            state=state,
            video_id=video_id,
            subtitles=subtitles,
            font="NotoSansSC",
            font_size=24,
            position="bottom"
        )
        
        return result
    
    async def apply_effects(
        self,
        state: ComicDramaState,
        video_id: str,
        effects: List[Dict]
    ) -> Dict[str, Any]:
        """
        应用视觉效果
        
        Args:
            state: 当前状态
            video_id: 视频 ID
            effects: 效果列表
            
        Returns:
            应用结果
        """
        from app.agent.tools.editing_tools import ApplyFilterTool
        
        apply_filter_tool = ApplyFilterTool()
        results = []
        
        for effect in effects:
            effect_type = effect.get("type", "color_correction")
            params = effect.get("params", {})
            
            result = await apply_filter_tool.execute(
                state=state,
                video_id=video_id,
                filter_type=effect_type,
                filter_params=params
            )
            results.append(result)
        
        success_count = sum(1 for r in results if r.get("success"))
        
        return {
            "success": success_count > 0,
            "video_id": video_id,
            "effects_applied": success_count,
            "total_effects": len(effects)
        }
    
    async def final_edit(
        self,
        state: ComicDramaState,
        quality: str = "high",
        resolution: str = "1080p"
    ) -> Dict[str, Any]:
        """
        最终剪辑
        
        Args:
            state: 当前状态
            quality: 质量
            resolution: 分辨率
            
        Returns:
            最终输出
        """
        assembled_videos = state.get("assembled_videos", [])
        
        if not assembled_videos:
            result = await self.assemble_video(state)
            if not result["success"]:
                return result
            assembled_videos = state.get("assembled_videos", [])
        
        main_video = assembled_videos[0]
        video_id = main_video.get("id")
        
        bgm = state.get("background_music")
        if bgm:
            await self.add_music_and_sfx(
                state=state,
                video_id=video_id,
                bgm_url=bgm.get("music_prompt")
            )
        
        subtitle_result = await self.add_subtitles_to_video(
            state=state,
            video_id=video_id
        )
        
        render_result = await self.final_render_tool.execute(
            state=state,
            quality=quality,
            resolution=resolution
        )
        
        if render_result.get("success"):
            state["final_video"] = {
                "url": render_result.get("output_url"),
                "duration": render_result.get("duration"),
                "quality": quality,
                "resolution": render_result.get("resolution"),
                "format": render_result.get("format"),
                "created_at": ""
            }
        
        return render_result
    
    async def create_alternative_cut(
        self,
        state: ComicDramaState,
        cut_type: str,
        target_duration: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        创建替代剪辑版本
        
        Args:
            state: 当前状态
            cut_type: 剪辑类型（trailer/teaser/short）
            target_duration: 目标时长（秒）
            
        Returns:
            替代版本信息
        """
        video_segments = state.get("video_segments", [])
        audio_segments = state.get("audio_segments", [])
        
        if cut_type == "trailer":
            selected_segments = video_segments[:3] if len(video_segments) >= 3 else video_segments
            target_duration = target_duration or 60
        elif cut_type == "teaser":
            selected_segments = video_segments[:1] if video_segments else []
            target_duration = target_duration or 30
        elif cut_type == "short":
            selected_segments = video_segments[:2] if len(video_segments) >= 2 else video_segments
            target_duration = target_duration or 45
        else:
            selected_segments = video_segments
            target_duration = target_duration or 120
        
        video_ids = [v.get("id") for v in selected_segments]
        
        output_filename = f"{cut_type}_{state.get('creation_uuid')}.mp4"
        
        result = await self.concatenate_tool.execute(
            state=state,
            video_ids=video_ids,
            output_filename=output_filename,
            transition_effect="fade"
        )
        
        if result.get("success"):
            return {
                "success": True,
                "cut_type": cut_type,
                "video_url": result.get("output_url"),
                "duration": result.get("duration"),
                "target_duration": target_duration,
                "segment_count": len(video_ids)
            }
        
        return {"success": False, "error": result.get("error")}


# 导出节点函数
async def editing_node(state: ComicDramaState) -> ComicDramaState:
    """
    LangGraph 节点：剪辑
    """
    editor = VideoEditor()
    
    result = await editor.assemble_video(state)
    
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    
    if result["success"]:
        messages.append({
            "role": "system",
            "content": f"视频组装完成: {result.get('segment_count')} 个片段"
        })
    else:
        errors.append(f"视频组装失败: {result.get('error')}")
    
    return {
        "messages": messages,
        "errors": errors
    }


async def final_edit_node(state: ComicDramaState) -> ComicDramaState:
    """
    LangGraph 节点：最终剪辑
    """
    editor = VideoEditor()
    
    result = await editor.final_edit(
        state=state,
        quality="high",
        resolution="1080p"
    )
    
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    
    if result.get("success"):
        messages.append({
            "role": "system",
            "content": f"🎉 最终视频生成完成！时长: {result.get('duration')}秒"
        })
    else:
        errors.append(f"最终剪辑失败: {result.get('error')}")
    
    return {
        "messages": messages,
        "errors": errors
    }
