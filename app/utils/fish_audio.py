"""
Fish Audio TTS 工具类
用于调用 Fish Audio 的文本转语音服务
"""

import os
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal, Iterator
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from app.core.config import settings
from app.core.logger import logger

from fishaudio import FishAudio
from fishaudio.utils import save

# TTS 配置
TTS_TIMEOUT = 60  # 超时时间（秒）
TTS_MAX_RETRIES = 3  # 最大重试次数
TTS_RETRY_DELAY = 2  # 重试间隔（秒）


class FishAudioClient:
    """Fish Audio TTS 客户端
    
    统一管理 Fish Audio API 调用，支持文本转语音功能
    """
    
    def __init__(self, api_key: str = None):
        """
        初始化 Fish Audio 客户端
        
        Args:
            api_key: Fish Audio API 密钥，默认从配置读取
        """
        self.api_key = api_key or settings.FISH_AUDIO_API_KEY
        
        if not self.api_key:
            raise ValueError("Fish Audio API Key 未配置")
        
        # 初始化 Fish Audio 客户端
        self.client = FishAudio(api_key=self.api_key)
        
        logger.info("Fish Audio 客户端初始化成功")
    
    def list_voices(
        self, 
        language: str = "zh", 
        page_size: int = 20, 
        page_number: int = 1
    ) -> list:
        """
        获取可用的语音模型列表
        
        Args:
            language: 语言代码，如 "zh", "en" 等
            page_size: 每页数量
            page_number: 页码
            
        Returns:
            语音模型列表
        """
        try:
            voices = self.client.voices.list(
                language=language, 
                page_size=page_size, 
                page_number=page_number
            )
            logger.info(f"获取语音列表成功，共 {len(voices)} 个")
            return voices
        except Exception as e:
            logger.error(f"获取语音列表失败: {e}")
            raise
    
    def get_voice(self, voice_id: str):
        """
        获取指定语音模型的详细信息
        
        Args:
            voice_id: 语音模型 ID
            
        Returns:
            语音模型详情
        """
        try:
            voice = self.client.voices.retrieve(voice_id)
            logger.info(f"获取语音模型成功: {voice.title}")
            return voice
        except Exception as e:
            logger.error(f"获取语音模型失败: {e}")
            raise
    
    def _do_tts_convert(
        self,
        text: str,
        voice_id: str,
        format: str,
        latency: str
    ) -> bytes:
        """实际执行 TTS 转换（内部方法）"""
        return self.client.tts.convert(
            text=text,
            reference_id=voice_id,
            format=format,
            latency=latency
        )
    
    def text_to_speech(
        self,
        text: str,
        reference_id: str = None,
        format: Literal["mp3", "wav", "pcm", "opus"] = "mp3",
        latency: Literal["normal", "balanced"] = "normal"
    ) -> bytes:
        """
        文本转语音（带超时和重试机制）
        
        Args:
            text: 要转换的文本
            reference_id: 语音模型 ID，不传则使用默认语音
            format: 音频格式，可选 "mp3", "wav", "pcm", "opus"
            latency: 延迟模式，"normal" 或 "balanced"
            
        Returns:
            音频字节数据
            
        Raises:
            Exception: TTS 转换失败
        """
        # 使用配置中的默认语音 ID，如果没有传入 reference_id
        voice_id = reference_id or settings.FISH_AUDIO_DEFAULT_VOICE_ID
        
        # 截取文本预览用于日志（最多50字符）
        text_preview = text[:50] + "..." if len(text) > 50 else text
        
        logger.info(f"开始 TTS 转换，文本长度: {len(text)}，语音模型: {voice_id}")
        logger.debug(f"TTS 转换文本内容: {text}")  # 完整文本记录到 debug 级别
        
        last_error = None
        
        for attempt in range(1, TTS_MAX_RETRIES + 1):
            try:
                logger.info(f"TTS 转换尝试 {attempt}/{TTS_MAX_RETRIES}，文本预览: {text_preview}")
                
                # 使用线程池实现超时控制
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        self._do_tts_convert,
                        text=text,
                        voice_id=voice_id,
                        format=format,
                        latency=latency
                    )
                    
                    try:
                        audio = future.result(timeout=TTS_TIMEOUT)
                    except FuturesTimeoutError:
                        raise TimeoutError(f"TTS 转换超时（{TTS_TIMEOUT}秒）")
                
                # 检查音频大小
                audio_size = len(audio) if audio else 0
                if audio_size == 0:
                    error_msg = f"TTS 转换返回空音频（0 bytes），文本: {text_preview}"
                    logger.warning(error_msg)
                    logger.warning(f"空音频对应的完整文本: {text}")
                    raise ValueError(error_msg)
                
                logger.info(f"TTS 转换成功，音频大小: {audio_size} bytes")
                return audio
                
            except TimeoutError as e:
                last_error = e
                logger.warning(f"TTS 转换超时（尝试 {attempt}/{TTS_MAX_RETRIES}）: {e}")
                logger.warning(f"超时对应的文本: {text}")
                
            except ValueError as e:
                # 空音频错误
                last_error = e
                logger.warning(f"TTS 转换返回空音频（尝试 {attempt}/{TTS_MAX_RETRIES}）")
                
            except Exception as e:
                last_error = e
                logger.warning(f"TTS 转换失败（尝试 {attempt}/{TTS_MAX_RETRIES}）: {e}")
                logger.warning(f"失败对应的文本: {text}")
            
            # 如果不是最后一次尝试，等待后重试
            if attempt < TTS_MAX_RETRIES:
                logger.info(f"等待 {TTS_RETRY_DELAY} 秒后重试...")
                time.sleep(TTS_RETRY_DELAY)
        
        # 所有重试都失败
        error_msg = f"TTS 转换失败，已重试 {TTS_MAX_RETRIES} 次: {last_error}"
        logger.error(error_msg)
        logger.error(f"最终失败的文本内容: {text}")
        raise Exception(error_msg)
    
    def text_to_speech_file(
        self,
        text: str,
        output_path: str = None,
        reference_id: str = None,
        format: Literal["mp3", "wav", "pcm", "opus"] = "mp3",
        latency: Literal["normal", "balanced"] = "normal"
    ) -> str:
        """
        文本转语音并保存到文件
        
        Args:
            text: 要转换的文本
            output_path: 输出文件路径，不传则自动生成
            reference_id: 语音模型 ID
            format: 音频格式
            latency: 延迟模式
            
        Returns:
            保存的文件路径
        """
        try:
            # 生成音频
            audio = self.text_to_speech(
                text=text,
                reference_id=reference_id,
                format=format,
                latency=latency
            )
            
            # 如果没有指定输出路径，自动生成
            if output_path is None:
                # 创建 audio_output 目录
                app_dir = Path(__file__).parent.parent.parent
                audio_dir = app_dir / "audio_output"
                audio_dir.mkdir(exist_ok=True)
                
                # 生成文件名
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                output_path = str(audio_dir / f"tts_{timestamp}.{format}")
            
            # 保存音频文件（audio 已经是 bytes）
            with open(output_path, 'wb') as f:
                f.write(audio)
            
            logger.info(f"音频已保存到: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"保存音频文件失败: {e}")
            raise
    
    def text_to_speech_bytes(
        self,
        text: str,
        reference_id: str = None,
        format: Literal["mp3", "wav", "pcm", "opus"] = "mp3",
        latency: Literal["normal", "balanced"] = "normal"
    ) -> bytes:
        """
        文本转语音并返回字节数据（带超时和重试机制）
        
        Args:
            text: 要转换的文本
            reference_id: 语音模型 ID
            format: 音频格式
            latency: 延迟模式
            
        Returns:
            音频字节数据
        """
        text_preview = text[:50] + "..." if len(text) > 50 else text
        
        try:
            # text_to_speech 已经包含超时和重试机制
            audio_bytes = self.text_to_speech(
                text=text,
                reference_id=reference_id,
                format=format,
                latency=latency
            )
            
            # 再次检查音频大小（双重保险）
            if not audio_bytes or len(audio_bytes) == 0:
                logger.error(f"TTS 返回空音频，文本: {text}")
                raise ValueError(f"TTS 返回空音频，文本: {text_preview}")
            
            logger.info(f"TTS 转换完成，音频大小: {len(audio_bytes)} bytes")
            return audio_bytes
            
        except Exception as e:
            logger.error(f"TTS 转换为字节失败: {e}")
            logger.error(f"失败的文本内容: {text}")
            raise


# 全局客户端实例（延迟初始化）
_fish_audio_client: Optional[FishAudioClient] = None


def get_fish_audio_client() -> FishAudioClient:
    """
    获取 Fish Audio 客户端单例
    
    Returns:
        FishAudioClient 实例
    """
    global _fish_audio_client
    if _fish_audio_client is None:
        _fish_audio_client = FishAudioClient()
    return _fish_audio_client

