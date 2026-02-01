


@celery_app.task(bind=True, name="agent.generate_shot_audio_batch")
def agent_generate_shot_audio_batch_task(
    self,
    creation_uuid: str,
    shot_ids: List[int],
    force_regenerate: bool = False,
) -> Dict[str, Any]:
    """
    批量生成 Shot 的 Narration 音频任务

    使用 GenerateNarrationAudioBatchTool 为每个 shot 的 narration 数组生成音频：
    1. 解析 narration 数组
    2. 根据说话者获取 voice_id 和 voice_speed
    3. 根据情绪添加情感标签
    4. 生成音频并上传到 US3
    5. 保存音频 URL 到 shot.audio_url
    6. 保存音频历史到 shot.extra_data["audio_historys"]

    Args:
        creation_uuid: 创作项目 UUID
        shot_ids: Shot ID 列表
        force_regenerate: 是否强制重新生成

    Returns:
        {
            "status": "success" | "partial" | "failed",
            "results": [...],
            "success_count": int,
            "failed_count": int,
        }
    """
    try:
        logger.info(f"[Agent Task] 开始批量生成 Shot 音频: {len(shot_ids)} shots")

        import asyncio
        from app.agent.tools.audio_tools import GenerateNarrationAudioBatchTool
        from app.agent.state.schemas import ComicDramaState

        # 创建工具实例
        audio_batch_tool = GenerateNarrationAudioBatchTool()

        # 创建状态对象
        state = ComicDramaState(creation_uuid=creation_uuid)

        results = []
        success_count = 0
        failed_count = 0

        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        for i, shot_id in enumerate(shot_ids):
            progress = int((i / len(shot_ids)) * 90) + 5
            self.update_state(state='PROGRESS', meta={
                'progress': progress,
                'status': f'生成第 {i+1}/{len(shot_ids)} 个分镜音频...',
                'current_shot_id': shot_id,
            })

            try:
                # 调用异步工具生成音频
                result = loop.run_until_complete(
                    audio_batch_tool.execute(
                        state=state,
                        shot_id=shot_id,
                        force_regenerate=force_regenerate
                    )
                )

                if result.get("success"):
                    data = result.get("data", {})
                    results.append({
                        "shot_id": shot_id,
                        "status": "success",
                        "audio_url": data.get("audio_url"),
                        "audio_results_count": len(data.get("audio_results", [])),
                        "audio_historys_count": data.get("audio_historys_count", 0),
                    })
                    success_count += 1
                    logger.info(f"[Agent Task] Shot {shot_id} 音频生成成功")
                else:
                    error_msg = result.get("error", "未知错误")
                    results.append({
                        "shot_id": shot_id,
                        "status": "failed",
                        "error": error_msg,
                    })
                    failed_count += 1
                    logger.error(f"[Agent Task] Shot {shot_id} 音频生成失败: {error_msg}")

            except Exception as e:
                logger.error(f"[Agent Task] Shot {shot_id} 音频生成异常: {e}")
                results.append({
                    "shot_id": shot_id,
                    "status": "failed",
                    "error": str(e),
                })
                failed_count += 1

        loop.close()

        status = "success" if failed_count == 0 else "partial" if success_count > 0 else "failed"

        logger.info(f"[Agent Task] 批量 Shot 音频生成完成: success={success_count}, failed={failed_count}")

        return {
            "status": status,
            "results": results,
            "success_count": success_count,
            "failed_count": failed_count,
        }

    except Exception as e:
        logger.error(f"[Agent Task] 批量 Shot 音频生成任务失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "results": [],
            "success_count": 0,
            "failed_count": len(shot_ids),
        }
