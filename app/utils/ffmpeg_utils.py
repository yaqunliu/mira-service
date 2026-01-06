"""
FFmpeg工具类 - 用于视频音频处理
"""
import os
import subprocess
import tempfile
from typing import Tuple, Optional
from app.core.logger import logger


class FFmpegUtils:
    """FFmpeg工具类"""

    @staticmethod
    def check_ffmpeg_installed() -> bool:
        """检查系统是否安装了ffmpeg"""
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"检查ffmpeg安装失败: {str(e)}")
            return False

    @staticmethod
    def separate_audio_video(
        input_video_path: str,
        output_video_path: Optional[str] = None,
        output_audio_path: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        分离视频和音频

        Args:
            input_video_path: 输入视频文件路径
            output_video_path: 输出无音频视频路径（可选）
            output_audio_path: 输出音频路径（可选）

        Returns:
            (静音视频路径, 音频路径)
        """
        try:
            # 检查输入文件是否存在
            if not os.path.exists(input_video_path):
                raise FileNotFoundError(f"输入视频文件不存在: {input_video_path}")

            # 如果未指定输出路径，使用临时文件
            if output_video_path is None:
                video_fd, output_video_path = tempfile.mkstemp(suffix='_silent.mp4')
                os.close(video_fd)

            if output_audio_path is None:
                audio_fd, output_audio_path = tempfile.mkstemp(suffix='.mp3')
                os.close(audio_fd)

            logger.info(f"开始分离音视频: {input_video_path}")

            # 1. 提取无音频的视频流（保留视频编码，移除音频）
            video_cmd = [
                'ffmpeg',
                '-i', input_video_path,
                '-an',  # 移除音频
                '-c:v', 'copy',  # 复制视频流（不重新编码）
                '-y',  # 覆盖输出文件
                output_video_path
            ]

            result = subprocess.run(
                video_cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )

            if result.returncode != 0:
                logger.error(f"提取视频失败: {result.stderr}")
                raise Exception(f"FFmpeg提取视频失败: {result.stderr}")

            logger.info(f"视频提取成功: {output_video_path}")

            # 2. 提取音频流 - 使用MP3格式
            audio_cmd = [
                'ffmpeg',
                '-i', input_video_path,
                '-vn',  # 移除视频
                '-acodec', 'libmp3lame',  # 使用MP3编码
                '-ab', '192k',  # 音频比特率
                '-ar', '44100',  # 采样率
                '-y',  # 覆盖输出文件
                output_audio_path
            ]

            result = subprocess.run(
                audio_cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )

            if result.returncode != 0:
                logger.error(f"提取音频失败: {result.stderr}")
                # 音频提取失败时，仍然返回视频（可能原视频没有音频）
                logger.warning(f"视频可能没有音频轨道，返回静音视频")
                return output_video_path, None

            logger.info(f"音频提取成功: {output_audio_path}")

            return output_video_path, output_audio_path

        except Exception as e:
            logger.error(f"分离音视频失败: {str(e)}")
            raise

    @staticmethod
    def get_video_info(video_path: str) -> dict:
        """
        获取视频信息（时长、分辨率等）

        Args:
            video_path: 视频文件路径

        Returns:
            视频信息字典
        """
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration:stream=width,height,codec_name',
                '-of', 'json',
                video_path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                raise Exception(f"FFprobe failed: {result.stderr}")

            import json
            info = json.loads(result.stdout)

            return {
                'duration': float(info.get('format', {}).get('duration', 0)),
                'width': info.get('streams', [{}])[0].get('width'),
                'height': info.get('streams', [{}])[0].get('height'),
                'video_codec': info.get('streams', [{}])[0].get('codec_name')
            }

        except Exception as e:
            logger.error(f"获取视频信息失败: {str(e)}")
            return {}

    @staticmethod
    def has_audio_stream(video_path: str) -> bool:
        """
        检查视频是否包含音频流

        Args:
            video_path: 视频文件路径

        Returns:
            是否包含音频
        """
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-select_streams', 'a',
                '-show_entries', 'stream=codec_type',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            return 'audio' in result.stdout

        except Exception as e:
            logger.error(f"检查音频流失败: {str(e)}")
            return False

    @staticmethod
    def trim_video_clip(input_path: str, output_path: str, start: float, end: float, apply_opacity: float = 1.0) -> None:
        """
        裁剪视频片段

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            start: 开始时间（秒）
            end: 结束时间（秒）
            apply_opacity: 透明度（0.0-1.0）
        """
        try:
            duration = end - start
            filter_complex = f"trim=start={start}:duration={duration},setpts=PTS-STARTPTS"

            if apply_opacity < 1.0:
                filter_complex += f",colorchannelmixer=aa={apply_opacity}"

            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-vf', filter_complex,
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-y',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                raise Exception(f"视频裁剪失败: {result.stderr}")

            logger.info(f"视频裁剪成功: {output_path}")

        except Exception as e:
            logger.error(f"裁剪视频失败: {str(e)}")
            raise

    @staticmethod
    def trim_audio_clip(input_path: str, output_path: str, start: float, end: float, volume: float = 1.0) -> None:
        """
        裁剪音频片段并调整音量

        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            start: 开始时间（秒）
            end: 结束时间（秒）
            volume: 音量倍数（0.0-2.0）
        """
        try:
            duration = end - start
            filter_complex = f"atrim=start={start}:duration={duration},asetpts=PTS-STARTPTS"

            if volume != 1.0:
                filter_complex += f",volume={volume}"

            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-af', filter_complex,
                '-c:a', 'libmp3lame',  # 使用 MP3 编码器匹配 .mp3 输出格式
                '-b:a', '192k',
                '-y',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

            if result.returncode != 0:
                raise Exception(f"音频裁剪失败: {result.stderr}")

            logger.info(f"音频裁剪成功: {output_path}")

        except Exception as e:
            logger.error(f"裁剪音频失败: {str(e)}")
            raise

    @staticmethod
    def generate_srt_file(text_clips: list, output_path: str) -> None:
        """
        从文本片段生成SRT字幕文件

        Args:
            text_clips: 文本片段列表，每个包含 text, startInTimeline, duration
            output_path: 输出SRT文件路径
        """
        try:
            def format_srt_time(seconds: float) -> str:
                """格式化时间为SRT格式 HH:MM:SS,mmm"""
                hours = int(seconds // 3600)
                minutes = int((seconds % 3600) // 60)
                secs = int(seconds % 60)
                millis = int((seconds % 1) * 1000)
                return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

            # 按时间轴位置排序
            sorted_clips = sorted(text_clips, key=lambda c: c.get('startInTimeline', 0))

            srt_lines = []
            for i, clip in enumerate(sorted_clips, 1):
                start_time = clip.get('startInTimeline', 0)
                duration = clip.get('duration', 0)
                end_time = start_time + duration
                text = clip.get('text', '')

                if not text:
                    continue

                srt_lines.append(f"{i}")
                srt_lines.append(f"{format_srt_time(start_time)} --> {format_srt_time(end_time)}")
                srt_lines.append(text)
                srt_lines.append("")  # 空行分隔

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(srt_lines))

            logger.info(f"SRT字幕文件生成成功: {output_path}")

        except Exception as e:
            logger.error(f"生成SRT字幕失败: {str(e)}")
            raise

    @staticmethod
    def convert_srt_to_ass(srt_path: str, ass_path: str, style_config: Optional[dict] = None) -> None:
        """
        将SRT字幕转换为ASS格式并应用样式

        Args:
            srt_path: 输入SRT文件路径
            ass_path: 输出ASS文件路径
            style_config: 样式配置（可选）
        """
        try:
            # 默认样式配置
            # ASS颜色格式: &HAABBGGRR (AA=透明度, BB=蓝, GG=绿, RR=红)
            # 透明度: 00=不透明, FF=完全透明
            default_style = {
                'fontname': 'Arial',
                'fontsize': 48,
                'primary_colour': '&H00FFFFFF',  # 白色文字 (完全不透明)
                'back_colour': 'B0000000',       # 黑色背景，透明度约30% (B0 ≈ 70%透明度)
                'border_style': 4,                # 4 = 带圆角的盒子背景
                'outline': 8,                     # 边框宽度（用于圆角半径）
                'alignment': 2,                   # 底部居中
                'margin_v': 50                    # 底部边距
            }

            if style_config:
                default_style.update(style_config)

            # ASS文件头部
            ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{default_style['fontname']},{default_style['fontsize']},{default_style['primary_colour']},&H000000FF,&H00000000,&H{default_style['back_colour']},-1,0,0,0,100,100,0,0,{default_style['border_style']},{default_style['outline']},0,{default_style['alignment']},10,10,{default_style['margin_v']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

            # 读取SRT并转换为ASS对话行
            def srt_time_to_ass(srt_time: str) -> str:
                """将SRT时间格式转换为ASS格式"""
                # SRT: 00:00:10,500 -> ASS: 0:00:10.50
                time_part, millis = srt_time.split(',')
                h, m, s = time_part.split(':')
                centisecs = int(millis) // 10
                return f"{int(h)}:{m}:{s}.{centisecs:02d}"

            with open(srt_path, 'r', encoding='utf-8') as srt_file:
                srt_content = srt_file.read()

            # 解析SRT条目
            entries = srt_content.strip().split('\n\n')
            ass_dialogues = []

            for entry in entries:
                lines = entry.strip().split('\n')
                if len(lines) < 3:
                    continue

                # 解析时间行
                time_line = lines[1]
                if ' --> ' not in time_line:
                    continue

                start, end = time_line.split(' --> ')
                ass_start = srt_time_to_ass(start.strip())
                ass_end = srt_time_to_ass(end.strip())

                # 文本内容（可能多行）
                text = '\\N'.join(lines[2:])  # \\N是ASS的换行符

                ass_dialogues.append(
                    f"Dialogue: 0,{ass_start},{ass_end},Default,,0,0,0,,{text}"
                )

            # 写入ASS文件
            with open(ass_path, 'w', encoding='utf-8') as ass_file:
                ass_file.write(ass_header)
                ass_file.write('\n'.join(ass_dialogues))

            logger.info(f"ASS字幕文件生成成功: {ass_path}")

        except Exception as e:
            logger.error(f"SRT转ASS失败: {str(e)}")
            raise

    @staticmethod
    def burn_subtitles(video_path: str, subtitle_path: str, output_path: str) -> None:
        """
        将字幕烧录到视频中

        Args:
            video_path: 输入视频路径
            subtitle_path: ASS字幕文件路径
            output_path: 输出视频路径
        """
        try:
            # 在Windows上需要转义路径中的特殊字符
            subtitle_path_escaped = subtitle_path.replace('\\', '/').replace(':', '\\:')

            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-vf', f"ass={subtitle_path_escaped}",
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-c:a', 'copy',  # 复制音频流
                '-y',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

            if result.returncode != 0:
                raise Exception(f"字幕烧录失败: {result.stderr}")

            logger.info(f"字幕烧录成功: {output_path}")

        except Exception as e:
            logger.error(f"烧录字幕失败: {str(e)}")
            raise

    @staticmethod
    def combine_video_audio(video_path: str, audio_path: str, output_path: str) -> None:
        """
        合并视频和音频流

        Args:
            video_path: 输入视频路径
            audio_path: 输入音频路径
            output_path: 输出视频路径
        """
        try:
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-i', audio_path,
                '-c:v', 'copy',  # 复制视频流
                '-c:a', 'aac',
                '-b:a', '192k',
                '-map', '0:v:0',  # 使用第一个输入的视频流
                '-map', '1:a:0',  # 使用第二个输入的音频流
                '-shortest',      # 使用最短的流作为输出长度
                '-movflags', '+faststart',  # 优化web播放
                '-y',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

            if result.returncode != 0:
                raise Exception(f"合并视频音频失败: {result.stderr}")

            logger.info(f"视频音频合并成功: {output_path}")

        except Exception as e:
            logger.error(f"合并视频音频失败: {str(e)}")
            raise

    @staticmethod
    def concat_videos_with_timeline(clips_info: list, output_path: str, total_duration: float) -> None:
        """
        根据时间轴配置合并多个视频片段

        Args:
            clips_info: 片段信息列表，每个包含 path, startInTimeline, duration
            output_path: 输出视频路径
            total_duration: 总时长（秒）
        """
        try:
            if not clips_info:
                raise ValueError("没有视频片段需要合并")

            # 按时间轴位置排序
            sorted_clips = sorted(clips_info, key=lambda c: c.get('startInTimeline', 0))

            # 构建filter_complex
            filter_parts = []
            current_time = 0.0

            for i, clip in enumerate(sorted_clips):
                clip_start = clip.get('startInTimeline', 0)
                clip_duration = clip.get('duration', 0)
                clip_path = clip.get('path', '')

                # 如果当前时间和片段开始时间之间有间隙，插入黑屏
                if clip_start > current_time:
                    gap_duration = clip_start - current_time
                    filter_parts.append(
                        f"color=c=black:s=1920x1080:d={gap_duration}:r=30[gap{i}]"
                    )

                current_time = clip_start + clip_duration

            # 使用concat协议连接所有片段
            if len(sorted_clips) == 1:
                # 单个片段，直接复制
                cmd = [
                    'ffmpeg',
                    '-i', sorted_clips[0]['path'],
                    '-c:v', 'libx264',
                    '-preset', 'medium',
                    '-crf', '23',
                    '-y',
                    output_path
                ]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

                if result.returncode != 0:
                    raise Exception(f"视频复制失败: {result.stderr}")
            else:
                # 多个片段，需要concat
                # 创建临时文件列表
                import tempfile
                fd, concat_file = tempfile.mkstemp(suffix='.txt')

                try:
                    with os.fdopen(fd, 'w') as f:
                        for clip in sorted_clips:
                            f.write(f"file '{clip['path']}'\n")

                    cmd = [
                        'ffmpeg',
                        '-f', 'concat',
                        '-safe', '0',
                        '-i', concat_file,
                        '-c:v', 'libx264',
                        '-preset', 'medium',
                        '-crf', '23',
                        '-y',
                        output_path
                    ]

                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

                    if result.returncode != 0:
                        raise Exception(f"视频合并失败: {result.stderr}")

                finally:
                    if os.path.exists(concat_file):
                        os.remove(concat_file)

            logger.info(f"视频合并成功: {output_path}")

        except Exception as e:
            logger.error(f"合并视频失败: {str(e)}")
            raise

    @staticmethod
    def concat_audios_with_timeline(clips_info: list, output_path: str, total_duration: float) -> None:
        """
        根据时间轴配置合并多个音频片段

        Args:
            clips_info: 片段信息列表，每个包含 path, startInTimeline, duration, volume
            output_path: 输出音频路径
            total_duration: 总时长（秒）
        """
        try:
            if not clips_info:
                # 生成静音音频
                cmd = [
                    'ffmpeg',
                    '-f', 'lavfi',
                    '-i', f'anullsrc=channel_layout=stereo:sample_rate=44100:duration={total_duration}',
                    '-c:a', 'libmp3lame',  # 使用 MP3 编码器匹配 .mp3 输出格式
                    '-b:a', '192k',
                    '-y',
                    output_path
                ]
                subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                logger.info(f"生成静音音频: {output_path}")
                return

            # 按时间轴位置排序
            sorted_clips = sorted(clips_info, key=lambda c: c.get('startInTimeline', 0))

            # 构建复杂filter
            filter_complex = []
            input_args = []

            for i, clip in enumerate(sorted_clips):
                input_args.extend(['-i', clip['path']])

                start_time = clip.get('startInTimeline', 0)
                volume = clip.get('volume', 1.0)

                # 使用adelay添加延迟（毫秒）
                delay_ms = int(start_time * 1000)
                filter_str = f"[{i}:a]volume={volume},adelay={delay_ms}|{delay_ms}[a{i}]"
                filter_complex.append(filter_str)

            # 混合所有音频
            mix_inputs = ''.join([f"[a{i}]" for i in range(len(sorted_clips))])
            filter_complex.append(f"{mix_inputs}amix=inputs={len(sorted_clips)}:duration=longest[aout]")

            cmd = [
                'ffmpeg',
                *input_args,
                '-filter_complex', ';'.join(filter_complex),
                '-map', '[aout]',
                '-c:a', 'libmp3lame',  # 使用 MP3 编码器匹配 .mp3 输出格式
                '-b:a', '192k',
                '-t', str(total_duration),  # 限制总时长
                '-y',
                output_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

            if result.returncode != 0:
                raise Exception(f"音频合并失败: {result.stderr}")

            logger.info(f"音频合并成功: {output_path}")

        except Exception as e:
            logger.error(f"合并音频失败: {str(e)}")
            raise
