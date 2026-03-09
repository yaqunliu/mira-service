"""
IndexTTS TTS 工具类
用于调用 Modelverse 平台的 IndexTTS 文本转语音服务
API 兼容 OpenAI TTS 格式
"""

import time
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal, Union, Dict, List, BinaryIO
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import httpx

from app.core.config import settings
from app.core.logger import logger

INDEX_TTS_TIMEOUT = 60
INDEX_TTS_MAX_RETRIES = 3
INDEX_TTS_RETRY_DELAY = 2
INDEX_TTS_MAX_TEXT_LENGTH = 600


class IndexTTSModel(str, Enum):
    """IndexTTS 模型枚举"""
    
    INDEX_TTS_2 = "IndexTeam/IndexTTS-2"
    
    @property
    def name(self) -> str:
        """获取模型显示名称"""
        names = {
            IndexTTSModel.INDEX_TTS_2: "IndexTTS-2",
        }
        return names.get(self, self.value)
    
    @property
    def description(self) -> str:
        """获取模型描述"""
        descriptions = {
            IndexTTSModel.INDEX_TTS_2: "IndexTeam 高质量中文语音合成模型，支持多种内置音色和自定义音色",
        }
        return descriptions.get(self, "")
    
    @property
    def max_text_length(self) -> int:
        """获取最大文本长度"""
        return INDEX_TTS_MAX_TEXT_LENGTH
    
    def __str__(self) -> str:
        return f"{self.name} ({self.value})"
    
    def __repr__(self) -> str:
        return f"<IndexTTSModel.{self.name}: '{self.value}'>"


class IndexTTSVoice(str, Enum):
    """
    IndexTTS 内置音色枚举
    
    可选值：
    - jack_cheng: 男声
    - sales_voice: 销售音色
    - crystla_liu: 女声
    - stephen_chow: 周星驰风格
    - xiaoyueyue: 小月月
    - mkas: MKAS 音色
    - entertain: 娱乐音色
    - novel: 小说音色
    - movie: 电影音色
    """
    
    JACK_CHENG = "jack_cheng"
    SALES_VOICE = "sales_voice"
    CRYSTLA_LIU = "crystla_liu"
    STEPHEN_CHOW = "stephen_chow"
    XIAOYUEYUE = "xiaoyueyue"
    MKAS = "mkas"
    ENTERTAIN = "entertain"
    NOVEL = "novel"
    MOVIE = "movie"
    
    @property
    def description(self) -> str:
        """获取音色描述"""
        descriptions = {
            IndexTTSVoice.JACK_CHENG: "男声",
            IndexTTSVoice.SALES_VOICE: "销售音色",
            IndexTTSVoice.CRYSTLA_LIU: "女声",
            IndexTTSVoice.STEPHEN_CHOW: "周星驰风格",
            IndexTTSVoice.XIAOYUEYUE: "小月月",
            IndexTTSVoice.MKAS: "MKAS 音色",
            IndexTTSVoice.ENTERTAIN: "娱乐音色",
            IndexTTSVoice.NOVEL: "小说音色",
            IndexTTSVoice.MOVIE: "电影音色",
        }
        return descriptions.get(self, "")


class IndexTTSClient:
    """
    IndexTTS 客户端
    
    统一管理 Modelverse 平台的 IndexTTS API 调用
    支持文本转语音、自定义音色管理等功能
    """
    
    API_BASE_URL = "https://api.modelverse.cn"
    
    def __init__(self, api_key: str = None, model: IndexTTSModel = None):
        """
        初始化 IndexTTS 客户端
        
        Args:
            api_key: Modelverse API 密钥，默认从配置读取
            model: TTS 模型，默认使用 IndexTTS-2
        """
        self.api_key = api_key or settings.OPENAI_API_KEY
        
        if not self.api_key:
            raise ValueError("IndexTTS API Key 未配置，请在环境变量中设置 OPENAI_API_KEY")
        
        self.model = model or IndexTTSModel.INDEX_TTS_2
        
        self._client = httpx.Client(
            base_url=self.API_BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=INDEX_TTS_TIMEOUT,
        )
        
        logger.info(f"IndexTTS 客户端初始化成功，使用模型: {self.model.name}")
    
    def _do_tts_convert(
        self,
        text: str,
        voice: str,
    ) -> bytes:
        """实际执行 TTS 转换（内部方法）"""
        payload = {
            "model": self.model.value,
            "input": text,
            "voice": voice,
        }
        
        response = self._client.post("/v1/audio/speech", json=payload)
        
        if response.status_code != 200:
            error_msg = f"TTS API 调用失败，状态码: {response.status_code}"
            try:
                error_data = response.json()
                if "error" in error_data:
                    error_msg = f"{error_msg}, 错误: {error_data['error'].get('message', '未知错误')}"
            except Exception:
                error_msg = f"{error_msg}, 响应: {response.text[:200]}"
            raise Exception(error_msg)
        
        return response.content
    
    def text_to_speech(
        self,
        text: str,
        voice: Union[str, IndexTTSVoice] = None,
    ) -> bytes:
        """
        文本转语音（带超时和重试机制）
        
        Args:
            text: 要转换的文本（最大 600 字符）
            voice: 音色，可以是内置音色名称或自定义音色 ID（uspeech:xxxx）
                   默认使用配置中的 INDEX_TTS_DEFAULT_VOICE
            
        Returns:
            音频字节数据（WAV 格式）
            
        Raises:
            Exception: TTS 转换失败
        """
        voice_id = voice or settings.INDEX_TTS_DEFAULT_VOICE or IndexTTSVoice.NOVEL.value
        
        if isinstance(voice, IndexTTSVoice):
            voice_id = voice.value
        else:
            voice_id = voice
        
        if len(text) > INDEX_TTS_MAX_TEXT_LENGTH:
            logger.warning(f"文本长度 {len(text)} 超过最大限制 {INDEX_TTS_MAX_TEXT_LENGTH}，将被截断")
            text = text[:INDEX_TTS_MAX_TEXT_LENGTH]
        
        text_preview = text[:50] + "..." if len(text) > 50 else text
        logger.info(f"开始 TTS 转换，文本长度: {len(text)}，音色: {voice_id}")
        logger.debug(f"TTS 转换文本内容: {text}")
        
        last_error = None
        
        for attempt in range(1, INDEX_TTS_MAX_RETRIES + 1):
            try:
                logger.info(f"TTS 转换尝试 {attempt}/{INDEX_TTS_MAX_RETRIES}，文本预览: {text_preview}")
                
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        self._do_tts_convert,
                        text=text,
                        voice=voice_id,
                    )
                    
                    try:
                        audio = future.result(timeout=INDEX_TTS_TIMEOUT)
                    except FuturesTimeoutError:
                        raise TimeoutError(f"TTS 转换超时（{INDEX_TTS_TIMEOUT}秒）")
                
                audio_size = len(audio) if audio else 0
                if audio_size == 0:
                    error_msg = f"TTS 转换返回空音频（0 bytes），文本: {text_preview}"
                    logger.warning(error_msg)
                    raise ValueError(error_msg)
                
                logger.info(f"TTS 转换成功，音频大小: {audio_size} bytes")
                return audio
                
            except TimeoutError as e:
                last_error = e
                logger.warning(f"TTS 转换超时（尝试 {attempt}/{INDEX_TTS_MAX_RETRIES}）: {e}")
                
            except ValueError as e:
                last_error = e
                logger.warning(f"TTS 转换返回空音频（尝试 {attempt}/{INDEX_TTS_MAX_RETRIES}）")
                
            except Exception as e:
                last_error = e
                logger.warning(f"TTS 转换失败（尝试 {attempt}/{INDEX_TTS_MAX_RETRIES}）: {e}")
            
            if attempt < INDEX_TTS_MAX_RETRIES:
                logger.info(f"等待 {INDEX_TTS_RETRY_DELAY} 秒后重试...")
                time.sleep(INDEX_TTS_RETRY_DELAY)
        
        error_msg = f"TTS 转换失败，已重试 {INDEX_TTS_MAX_RETRIES} 次: {last_error}"
        logger.error(error_msg)
        raise Exception(error_msg)
    
    def text_to_speech_file(
        self,
        text: str,
        output_path: str = None,
        voice: Union[str, IndexTTSVoice] = None,
    ) -> str:
        """
        文本转语音并保存到文件
        
        Args:
            text: 要转换的文本
            output_path: 输出文件路径，不传则自动生成
            voice: 音色
            
        Returns:
            保存的文件路径
        """
        try:
            audio = self.text_to_speech(text=text, voice=voice)
            
            if output_path is None:
                app_dir = Path(__file__).parent.parent.parent
                audio_dir = app_dir / "audio_output"
                audio_dir.mkdir(exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                output_path = str(audio_dir / f"index_tts_{timestamp}.wav")
            
            with open(output_path, 'wb') as f:
                f.write(audio)
            
            logger.info(f"音频已保存到: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"保存音频文件失败: {e}")
            raise
    
    def upload_voice(
        self,
        name: str,
        speaker_file: Union[str, Path, BinaryIO] = None,
        speaker_file_base64: str = None,
        speaker_url: str = None,
        emotion_file: Union[str, Path, BinaryIO] = None,
        emotion_file_base64: str = None,
        emotion_url: str = None,
        model: IndexTTSModel = None,
    ) -> str:
        """
        上传自定义音色
        
        Args:
            name: 音色名称
            speaker_file: 音色语料音频文件路径或文件对象（三选一必填）
            speaker_file_base64: 音色语料音频 Base64 字符串（三选一必填）
            speaker_url: 音色语料音频 URL（三选一必填）
            emotion_file: 情绪样例音频文件路径或文件对象（三选一可选）
            emotion_file_base64: 情绪样例音频 Base64 字符串（三选一可选）
            emotion_url: 情绪样例音频 URL（三选一可选）
            model: TTS 模型，默认使用当前模型
            
        Returns:
            自定义音色 ID（格式：uspeech:xxxx）
            
        Raises:
            ValueError: 参数错误
            Exception: 上传失败
        """
        if not any([speaker_file, speaker_file_base64, speaker_url]):
            raise ValueError("必须提供 speaker_file、speaker_file_base64 或 speaker_url 其中之一")
        
        used_model = model or self.model
        
        files = {}
        data = {
            "name": name,
            "model": used_model.value,
        }
        
        if speaker_file:
            if isinstance(speaker_file, (str, Path)):
                files["speaker_file"] = open(speaker_file, "rb")
            else:
                files["speaker_file"] = speaker_file
        elif speaker_file_base64:
            data["speaker_file_base64"] = speaker_file_base64
        elif speaker_url:
            data["speaker_url"] = speaker_url
        
        if emotion_file:
            if isinstance(emotion_file, (str, Path)):
                files["emotion_file"] = open(emotion_file, "rb")
            else:
                files["emotion_file"] = emotion_file
        elif emotion_file_base64:
            data["emotion_file_base64"] = emotion_file_base64
        elif emotion_url:
            data["emotion_url"] = emotion_url
        
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
            }
            
            if files:
                headers.pop("Content-Type", None)
                response = httpx.post(
                    f"{self.API_BASE_URL}/v1/audio/voice/upload",
                    headers=headers,
                    data=data,
                    files=files,
                    timeout=60,
                )
            else:
                response = httpx.post(
                    f"{self.API_BASE_URL}/v1/audio/voice/upload",
                    headers={**headers, "Content-Type": "application/json"},
                    json=data,
                    timeout=60,
                )
            
            if response.status_code != 200:
                error_msg = f"上传音色失败，状态码: {response.status_code}"
                try:
                    error_data = response.json()
                    if "error" in error_data:
                        error_msg = f"{error_msg}, 错误: {error_data['error'].get('message', '未知错误')}"
                except Exception:
                    error_msg = f"{error_msg}, 响应: {response.text[:200]}"
                raise Exception(error_msg)
            
            result = response.json()
            voice_id = result.get("id")
            logger.info(f"上传音色成功，音色 ID: {voice_id}")
            return voice_id
            
        finally:
            for f in files.values():
                if hasattr(f, 'close'):
                    f.close()
    
    def list_voices(self) -> List[Dict[str, str]]:
        """
        查询自定义音色列表
        
        Returns:
            自定义音色列表，每项包含 id 和 name
        """
        try:
            response = self._client.get("/v1/audio/voice/list")
            
            if response.status_code != 200:
                error_msg = f"查询音色列表失败，状态码: {response.status_code}"
                try:
                    error_data = response.json()
                    if "error" in error_data:
                        error_msg = f"{error_msg}, 错误: {error_data['error'].get('message', '未知错误')}"
                except Exception:
                    error_msg = f"{error_msg}, 响应: {response.text[:200]}"
                raise Exception(error_msg)
            
            result = response.json()
            voices = result.get("list", [])
            logger.info(f"查询音色列表成功，共 {len(voices)} 个音色")
            return voices
            
        except Exception as e:
            logger.error(f"查询音色列表失败: {e}")
            raise
    
    def delete_voice(self, voice_id: str) -> bool:
        """
        删除自定义音色
        
        Args:
            voice_id: 自定义音色 ID
            
        Returns:
            是否删除成功
        """
        try:
            response = self._client.post(
                "/v1/audio/voice/delete",
                json={"id": voice_id},
            )
            
            if response.status_code != 200:
                error_msg = f"删除音色失败，状态码: {response.status_code}"
                try:
                    error_data = response.json()
                    if "error" in error_data:
                        error_msg = f"{error_msg}, 错误: {error_data['error'].get('message', '未知错误')}"
                except Exception:
                    error_msg = f"{error_msg}, 响应: {response.text[:200]}"
                raise Exception(error_msg)
            
            result = response.json()
            success = result.get("success", False)
            logger.info(f"删除音色成功，音色 ID: {voice_id}")
            return success
            
        except Exception as e:
            logger.error(f"删除音色失败: {e}")
            raise
    
    def close(self):
        """关闭客户端连接"""
        self._client.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


_index_tts_client: Optional[IndexTTSClient] = None


def get_index_tts_client() -> IndexTTSClient:
    """
    获取 IndexTTS 客户端单例
    
    Returns:
        IndexTTSClient 实例
    """
    global _index_tts_client
    if _index_tts_client is None:
        _index_tts_client = IndexTTSClient()
    return _index_tts_client
