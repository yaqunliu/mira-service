"""
Fish Audio TTS 工具类
用于调用 Fish Audio 的文本转语音服务
"""

import os
import time
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Literal, Iterator, Union, Dict, List
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from app.core.config import settings
from app.core.logger import logger

from fishaudio import FishAudio
from fishaudio.utils import save

TTS_TIMEOUT = 60
TTS_MAX_RETRIES = 3
TTS_RETRY_DELAY = 2


class FishAudioModel(str, Enum):
    """Fish Audio TTS 模型枚举"""
    
    S1 = "s1"
    SPEECH_1_6 = "speech-1.6"
    SPEECH_1_5 = "speech-1.5"
    
    @property
    def name(self) -> str:
        """获取模型显示名称"""
        names = {
            FishAudioModel.S1: "Fish Audio S1",
            FishAudioModel.SPEECH_1_6: "Fish Speech 1.6",
            FishAudioModel.SPEECH_1_5: "Fish Speech 1.5",
        }
        return names.get(self, self.value)
    
    @property
    def description(self) -> str:
        """获取模型描述"""
        descriptions = {
            FishAudioModel.S1: "旗舰模型，行业领先质量，支持完整的情绪控制功能",
            FishAudioModel.SPEECH_1_6: "上一代模型，稳定可靠，支持基本情绪控制",
            FishAudioModel.SPEECH_1_5: "早期模型，可靠稳定，仅支持基本情绪，资源需求较低",
        }
        return descriptions.get(self, "")
    
    @property
    def parameters(self) -> str:
        """获取模型参数量"""
        params = {
            FishAudioModel.S1: "40亿参数",
            FishAudioModel.SPEECH_1_6: "未知",
            FishAudioModel.SPEECH_1_5: "未知",
        }
        return params.get(self, "")
    
    @property
    def wer(self) -> str:
        """获取词错误率"""
        wer_map = {
            FishAudioModel.S1: "0.8% (WER: 0.008)",
            FishAudioModel.SPEECH_1_6: "较低",
            FishAudioModel.SPEECH_1_5: "一般",
        }
        return wer_map.get(self, "")
    
    @property
    def emotional_control(self) -> str:
        """获取情绪控制能力"""
        emotions = {
            FishAudioModel.S1: "完整支持64+情绪表达",
            FishAudioModel.SPEECH_1_6: "基本情绪控制",
            FishAudioModel.SPEECH_1_5: "仅基本情绪",
        }
        return emotions.get(self, "")
    
    @property
    def performance(self) -> str:
        """获取性能评级"""
        perf = {
            FishAudioModel.S1: "⭐⭐⭐⭐⭐ 最佳",
            FishAudioModel.SPEECH_1_6: "⭐⭐⭐⭐ 良好",
            FishAudioModel.SPEECH_1_5: "⭐⭐⭐ 一般",
        }
        return perf.get(self, "")
    
    @property
    def supported_emotion_types(self) -> List[str]:
        """
        获取模型支持的情绪标签类型
        
        Returns:
            支持的标签类型列表
        """
        support_map = {
            FishAudioModel.S1: [
                "BasicEmotion",    # 基本情绪 (24种)
                "AdvancedEmotion", # 高级情绪 (25种)
                "ToneMarker",      # 语气标记 (5种)
                "AudioEffect",     # 音频效果 (10种)
                "SpecialEffect",   # 特殊效果 (5种)
            ],
            FishAudioModel.SPEECH_1_6: [
                "BasicEmotion",    # 基本情绪 (24种)
            ],
            FishAudioModel.SPEECH_1_5: [
                "BasicEmotion",    # 基本情绪 (24种)
            ],
        }
        return support_map.get(self, [])
    
    @property
    def total_emotion_count(self) -> int:
        """获取支持的情绪标签总数"""
        counts = {
            FishAudioModel.S1: 69,  # 24 + 25 + 5 + 10 + 5
            FishAudioModel.SPEECH_1_6: 24,
            FishAudioModel.SPEECH_1_5: 24,
        }
        return counts.get(self, 0)
    
    def supports_emotion_type(self, emotion_type: str) -> bool:
        """
        检查模型是否支持指定类型的情绪标签
        
        Args:
            emotion_type: 情绪类型名称，如 "BasicEmotion", "AdvancedEmotion" 等
            
        Returns:
            是否支持
        """
        return emotion_type in self.supported_emotion_types
    
    def supports_emotion(self, emotion_value: str) -> bool:
        """
        检查模型是否支持指定的情绪标签值
        
        Args:
            emotion_value: 情绪标签值，如 "happy", "excited" 等
            
        Returns:
            是否支持
        """
        from app.utils.fish_audio import (
            BasicEmotion, AdvancedEmotion, ToneMarker, AudioEffect, SpecialEffect
        )
        
        all_emotions = []
        all_emotions.extend([e.value for e in BasicEmotion])
        
        if self == FishAudioModel.S1:
            all_emotions.extend([e.value for e in AdvancedEmotion])
            all_emotions.extend([e.value for e in ToneMarker])
            all_emotions.extend([e.value for e in AudioEffect])
            all_emotions.extend([e.value for e in SpecialEffect])
        
        return emotion_value.lower() in [e.lower() for e in all_emotions]
    
    def get_supported_emotions_info(self) -> Dict[str, List[str]]:
        """
        获取模型支持的所有情绪标签详情
        
        Returns:
            分类的情绪标签字典
        """
        from app.utils.fish_audio import (
            BasicEmotion, AdvancedEmotion, ToneMarker, AudioEffect, SpecialEffect
        )
        
        result = {
            "basic_emotions": [],
            "advanced_emotions": [],
            "tone_markers": [],
            "audio_effects": [],
            "special_effects": [],
        }
        
        result["basic_emotions"] = [e.value for e in BasicEmotion]
        
        if self == FishAudioModel.S1:
            result["advanced_emotions"] = [e.value for e in AdvancedEmotion]
            result["tone_markers"] = [e.value for e in ToneMarker]
            result["audio_effects"] = [e.value for e in AudioEffect]
            result["special_effects"] = [e.value for e in SpecialEffect]
        
        return result
    
    def __str__(self) -> str:
        return f"{self.name} ({self.value})"
    
    def __repr__(self) -> str:
        return f"<FishAudioModel.{self.name}: '{self.value}'>"


class BasicEmotion(str, Enum):
    """
    基本情绪标签
    
    支持所有 Fish Audio 模型（S1, speech-1.6, speech-1.5）
    共24种基本情绪，适用于各种场景
    
    使用方法：将情绪标签用括号包裹，放在句首
    示例：(happy) 今天天气真好！
    
    情绪说明：
    - happy: 愉快、乐观的语调 - 好消息、问候
    - sad: 忧郁、低落的语调 - 同情、坏消息
    - angry: 沮丧、愤怒的语调 - 投诉、警告
    - excited: 充满活力、热情的语调 - 公告、庆祝
    - calm: 和平、放松的语调 - 指导、冥想
    - nervous: 焦虑、不确定的语调 - 免责声明、道歉
    - confident: 自信、肯定的语调 - 演示、销售
    - surprised: 震惊、惊奇的语调 - 反应、发现
    - satisfied: 满足、满意的语调 - 确认、评论
    - delighted: 非常高兴、快乐的语调 - 庆祝、赞美
    - scared: 害怕、恐惧的语调 - 警告、恐怖故事
    - worried: 担忧、困扰的语调 - 担忧、问题
    - upset: 不安、沮丧的语调 - 投诉、问题
    - frustrated: 恼火、愤怒的语调 - 技术问题、延误
    - depressed: 非常难过、绝望的语调 - 严肃话题
    - empathetic: 理解、关心的语调 - 支持、咨询
    - embarrassed: 羞愧、尴尬的语调 - 道歉、错误
    - disgusted: 反感、厌恶的语调 - 负面评价
    - moved: 感动的语调 - 感人时刻
    - proud: 骄傲、满足的语调 - 成就、赞美
    - relaxed: 轻松、自在的语调 - 日常对话
    - grateful: 感激、感谢的语调 - 感谢、致谢
    - curious: 好奇、感兴趣的语调 - 问题、探索
    - sarcastic: 讽刺、嘲弄的语调 - 幽默、批评
    """
    HAPPY = "happy"
    SAD = "sad"
    ANGRY = "angry"
    EXCITED = "excited"
    CALM = "calm"
    NERVOUS = "nervous"
    CONFIDENT = "confident"
    SURPRISED = "surprised"
    SATISFIED = "satisfied"
    DELIGHTED = "delighted"
    SCARED = "scared"
    WORRIED = "worried"
    UPSET = "upset"
    FRUSTRATED = "frustrated"
    DEPRESSED = "depressed"
    EMPATHETIC = "empathetic"
    EMBARRASSED = "embarrassed"
    DISGUSTED = "disgusted"
    MOVED = "moved"
    PROUD = "proud"
    RELAXED = "relaxed"
    GRATEFUL = "grateful"
    CURIOUS = "curious"
    SARCARTIC = "sarcastic"


class AdvancedEmotion(str, Enum):
    """
    高级情绪标签
    
    ⚠️ 仅支持 S1 模型（speech-1.6 和 speech-1.5 不支持）
    共25种高级情绪，提供更细腻的情感表达
    
    使用方法：将情绪标签用括号包裹，放在句首
    示例：(disappointed) 这让我很失望
    
    情绪说明：
    - disdainful: 轻蔑、鄙视的语调 - 批评、拒绝
    - unhappy: 不满、不快的语调 - 投诉、反馈
    - anxious: 非常担忧、不安的语调 - 紧急事务
    - hysterical: 失控情绪化的语调 - 极端反应
    - indifferent: 漠不关心、中性的语调 - 中性回应
    - uncertain: 怀疑、不确定的语调 - 推测、问题
    - doubtful: 怀疑、质疑的语调 - 不信、质疑
    - confused: 困惑、迷惑的语调 - 澄清请求
    - disappointed: 失望、不满的语调 - 未达预期
    - regretful: 抱歉、后悔的语调 - 道歉、错误
    - guilty: 内疚、负责任的语调 - 坦白、道歉
    - ashamed: 深度尴尬的语调 - 严重错误
    - jealous: 嫉妒、怨恨的语调 - 比较
    - envious: 羡慕、想要的语调 - 钦佩、渴望
    - hopeful: 对未来乐观的语调 - 未来计划
    - optimistic: 积极乐观的语调 - 鼓励
    - pessimistic: 消极悲观的语调 - 警告、怀疑
    - nostalgic: 怀念过去的语调 - 回忆、故事
    - lonely: 孤独、孤单的语调 - 情感内容
    - bored: 无聊、厌倦的语调 - 不感兴趣
    - contemptuous: 轻蔑的语调 - 强烈批评
    - sympathetic: 同情的语调 - 哀悼
    - compassionate: 深切关怀的语调 - 支持、帮助
    - determined: 坚定、果断的语调 - 目标、承诺
    - resigned: 接受失败的语调 - 放弃、接受
    """
    DISDAINFUL = "disdainful"
    UNHAPPY = "unhappy"
    ANXIOUS = "anxious"
    HYSTERICAL = "hysterical"
    INDIFFERENT = "indifferent"
    UNCERTAIN = "uncertain"
    DOUBTFUL = "doubtful"
    CONFUSED = "confused"
    DISAPPOINTED = "disappointed"
    REGRETFUL = "regretful"
    GUILTY = "guilty"
    ASHAMED = "ashamed"
    JEALOUS = "jealous"
    ENVIOUS = "envious"
    HOPEFUL = "hopeful"
    OPTIMISTIC = "optimistic"
    PESSIMISTIC = "pessimistic"
    NOSTALGIC = "nostalgic"
    LONELY = "lonely"
    BORED = "bored"
    CONTEMPTUOUS = "contemptuous"
    SYMPATHETIC = "sympathetic"
    COMPASSIONATE = "compassionate"
    DETERMINED = "determined"
    RESIGNED = "resigned"


class ToneMarker(str, Enum):
    """
    语气标记
    
    ⚠️ 仅支持 S1 模型（speech-1.6 和 speech-1.5 不支持）
    共5种语气标记，控制语音的音量和强度
    
    使用方法：将语气标记用括号包裹，可放在句中任意位置
    示例：他小声说 (whispering) 这是个秘密
    
    语气说明：
    - in a hurry: 匆忙、紧急的语调 - 时间敏感信息
    - shouting: 大声、呼喊的语调 - 引起注意
    - screaming: 非常大声、恐慌的语调 - 紧急、恐惧
    - whispering: 非常轻柔、秘密的语调 - 秘密、安静场景
    - soft tone: 温柔、柔和的语调 - 安抚、摇篮曲
    """
    IN_A_HURRY = "in a hurry"
    SHOUTING = "shouting"
    SCREAMING = "screaming"
    WHISPERING = "whispering"
    SOFT_TONE = "soft tone"


class AudioEffect(str, Enum):
    """
    音频效果
    
    ⚠️ 仅支持 S1 模型（speech-1.6 和 speech-1.5 不支持）
    共10种音频效果，添加自然的人类声音元素
    
    使用方法：将效果标签用括号包裹，放在句中任意位置
    示例：(laughing) 哈哈，这太有趣了！
    
    效果说明：
    - laughing: 完整的笑声 - 哈哈哈哈哈
    - chuckling: 轻声笑 - 嘿嘿
    - sobbing: 大声哭泣 - 呜呜呜
    - crying loudly: 剧烈哭泣 - 可选配文
    - sighing: 叹息/解脱或沮丧 - 唉
    - groaning: 沮丧的声音 - 呃
    - panting: 气喘吁吁 - 呼呼
    - gasping: 倒吸一口凉气 - 哈
    - yawning: 困倦的声音 - 哈欠
    - snoring: 睡觉打呼噜 - 呼噜
    """
    LAUGHING = "laughing"
    CHUCKLING = "chuckling"
    SOBBING = "sobbing"
    CRYING_LOUDLY = "crying loudly"
    SIGHING = "sighing"
    GROANING = "groaning"
    PANTING = "panting"
    GASPING = "gasping"
    YAWNING = "yawning"
    SNORING = "snoring"


class SpecialEffect(str, Enum):
    """
    特殊效果
    
    ⚠️ 仅支持 S1 模型（speech-1.6 和 speech-1.5 不支持）
    共5种特殊效果，用于添加场景氛围和背景音
    
    使用方法：将效果标签用括号包裹，放在句中任意位置
    示例：(audience laughing) 观众们都笑了
    
    效果说明：
    - audience laughing: 观众笑声 - 现场观众笑声
    - background laughter: 背景笑声 - 环境笑声
    - crowd laughing: 人群笑声 - 大群人笑声
    - break: 短暂停顿 - 句子中的短暂停顿
    - long-break: 长时间停顿 - 句子中的延长停顿
    """
    AUDIENCE_LAUGHING = "audience laughing"
    BACKGROUND_LAUGHTER = "background laughter"
    CROWD_LAUGHING = "crowd laughing"
    SHORT_PAUSE = "break"
    LONG_PAUSE = "long-break"


class EmotionTag:
    """情绪标签处理器"""
    
    EMOTION_PATTERNS = {
        BasicEmotion: re.compile(r'\((?:%s)\)' % '|'.join([e.value for e in BasicEmotion]), re.IGNORECASE),
        AdvancedEmotion: re.compile(r'\((?:%s)\)' % '|'.join([e.value for e in AdvancedEmotion]), re.IGNORECASE),
        ToneMarker: re.compile(r'\((?:%s)\)' % '|'.join([e.value for e in ToneMarker]), re.IGNORECASE),
        AudioEffect: re.compile(r'\((?:%s)\)' % '|'.join([e.value for e in AudioEffect]), re.IGNORECASE),
        SpecialEffect: re.compile(r'\((?:%s)\)' % '|'.join([e.value for e in SpecialEffect]), re.IGNORECASE),
    }
    
    @classmethod
    def extract_emotions(cls, text: str) -> Dict[str, List[str]]:
        """
        从文本中提取所有情绪标签
        
        Args:
            text: 包含情绪标签的文本
            
        Returns:
            分类的情绪标签字典
        """
        result = {
            "basic_emotions": [],
            "advanced_emotions": [],
            "tone_markers": [],
            "audio_effects": [],
            "special_effects": [],
        }
        
        text_lower = text.lower()
        
        for emotion_type, pattern in cls.EMOTION_PATTERNS.items():
            matches = pattern.findall(text)
            for match in matches:
                clean_match = match.strip('()')
                if emotion_type == BasicEmotion:
                    result["basic_emotions"].append(clean_match)
                elif emotion_type == AdvancedEmotion:
                    result["advanced_emotions"].append(clean_match)
                elif emotion_type == ToneMarker:
                    result["tone_markers"].append(clean_match)
                elif emotion_type == AudioEffect:
                    result["audio_effects"].append(clean_match)
                elif emotion_type == SpecialEffect:
                    result["special_effects"].append(clean_match)
        
        return result
    
    @classmethod
    def wrap_emotion(cls, text: str, emotion: Union[str, Enum]) -> str:
        """
        为文本添加情绪标签
        
        Args:
            text: 原始文本
            emotion: 情绪标签（字符串或枚举值）
            
        Returns:
            包裹情绪标签的文本
            
        Example:
            >>> EmotionTag.wrap_emotion("今天天气真好！", BasicEmotion.HAPPY)
            '(happy) 今天天气真好！'
        """
        emotion_value = emotion.value if isinstance(emotion, Enum) else emotion
        return f"({emotion_value}) {text}"
    
    @classmethod
    def wrap_multiple_emotions(cls, text: str, emotions: List[Union[str, Enum]]) -> str:
        """
        为文本添加多个情绪标签
        
        Args:
            text: 原始文本
            emotions: 情绪标签列表
            
        Returns:
            包裹多个情绪标签的文本
            
        Example:
            >>> EmotionTag.wrap_multiple_emotions("我很抱歉", [BasicEmotion.SAD, ToneMarker.WHISPERING])
            '(sad)(whispering) 我很抱歉'
        """
        emotion_prefix = ""
        for emotion in emotions:
            emotion_value = emotion.value if isinstance(emotion, Enum) else emotion
            emotion_prefix += f"({emotion_value})"
        return f"{emotion_prefix} {text}"
    
    @classmethod
    def has_emotion_tags(cls, text: str) -> bool:
        """
        检查文本是否包含情绪标签
        
        Args:
            text: 要检查的文本
            
        Returns:
            是否包含情绪标签
        """
        return any(pattern.search(text) for pattern in cls.EMOTION_PATTERNS.values())


class FishAudioClient:
    """Fish Audio TTS 客户端
    
    统一管理 Fish Audio API 调用，支持文本转语音功能
    """
    
    def __init__(self, api_key: str = None, model: FishAudioModel = None):
        """
        初始化 Fish Audio 客户端
        
        Args:
            api_key: Fish Audio API 密钥，默认从配置读取
            model: TTS 模型，默认使用配置中的 FISH_AUDIO_DEFAULT_MODEL
        """
        self.api_key = api_key or settings.FISH_AUDIO_API_KEY
        
        if not self.api_key:
            raise ValueError("Fish Audio API Key 未配置")
        
        # 初始化 Fish Audio 客户端
        self.client = FishAudio(api_key=self.api_key)
        
        # 设置默认模型
        if model is None:
            model_value = settings.FISH_AUDIO_DEFAULT_MODEL
            try:
                self.model = FishAudioModel(model_value)
            except ValueError:
                logger.warning(f"未知的 Fish Audio 模型: {model_value}，使用默认 S1 模型")
                self.model = FishAudioModel.S1
        else:
            self.model = model
        
        logger.info(f"Fish Audio 客户端初始化成功，使用模型: {self.model.name}")
    
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
        latency: str,
        speed: Optional[float] = None,
        emotions: Optional[List[Union[str, Enum]]] = None,
        model: FishAudioModel = None
    ) -> bytes:
        """实际执行 TTS 转换（内部方法）"""
        processed_text = text
        
        # 获取使用的模型
        used_model = model if model is not None else self.model
        
        # 检查情绪标签是否与模型兼容
        if emotions and len(emotions) > 0:
            # 检查是否有 S1 专属的情绪类型
            emotion_types_used = set()
            for emotion in emotions:
                emotion_str = emotion.value if isinstance(emotion, Enum) else str(emotion)
                if emotion_str in [e.value for e in AdvancedEmotion]:
                    emotion_types_used.add("AdvancedEmotion")
                elif emotion_str in [e.value for e in ToneMarker]:
                    emotion_types_used.add("ToneMarker")
                elif emotion_str in [e.value for e in AudioEffect]:
                    emotion_types_used.add("AudioEffect")
                elif emotion_str in [e.value for e in SpecialEffect]:
                    emotion_types_used.add("SpecialEffect")
            
            # 如果使用了 S1 专属情绪，但模型不是 S1，发出警告
            if emotion_types_used and used_model != FishAudioModel.S1:
                logger.warning(
                    f"模型 {used_model.name} 不支持以下高级情绪类型: {list(emotion_types_used)}，"
                    f"这些标签将被忽略。建议使用 S1 模型以获得完整的情绪控制功能。"
                )
                # 过滤掉不支持的情绪
                supported_emotions = []
                for emotion in emotions:
                    emotion_str = emotion.value if isinstance(emotion, Enum) else str(emotion)
                    if emotion_str not in [e.value for e in AdvancedEmotion] and \
                       emotion_str not in [e.value for e in ToneMarker] and \
                       emotion_str not in [e.value for e in AudioEffect] and \
                       emotion_str not in [e.value for e in SpecialEffect]:
                        supported_emotions.append(emotion)
                emotions = supported_emotions
            
            # 应用情绪标签
            if emotions and len(emotions) > 0:
                processed_text = EmotionTag.wrap_multiple_emotions(text, emotions)
                logger.debug(f"应用情绪标签后的文本: {processed_text}")
        
        kwargs = {
            "text": processed_text,
            "reference_id": voice_id,
            "format": format,
            "latency": latency
        }
        if speed is not None:
            kwargs["speed"] = speed
        # 添加模型参数（如果 API 支持）
        if used_model:
            kwargs["model"] = used_model.value
        return self.client.tts.convert(**kwargs)
    
    def text_to_speech(
        self,
        text: str,
        reference_id: str = None,
        format: Literal["mp3", "wav", "pcm", "opus"] = "mp3",
        latency: Literal["normal", "balanced"] = "normal",
        speed: Optional[float] = None,
        emotions: Optional[List[Union[str, Enum]]] = None,
        model: FishAudioModel = None
    ) -> bytes:
        """
        文本转语音（带超时和重试机制）
        
        Args:
            text: 要转换的文本
            reference_id: 语音模型 ID，不传则使用默认语音
            format: 音频格式，可选 "mp3", "wav", "pcm", "opus"
            latency: 延迟模式，"normal" 或 "balanced"
            speed: 语速参数，浮点数，通常范围 0.5-2.0
            emotions: 情绪标签列表，用于控制语音情感表达
            model: TTS 模型，可选 s1, speech-1.6, speech-1.5，默认使用配置中的默认模型
            
        Returns:
            音频字节数据
            
        Raises:
            Exception: TTS 转换失败
            
        Example:
            >>> client = FishAudioClient()
            >>> audio = client.text_to_speech(
            ...     text="今天天气真好！",
            ...     emotions=[BasicEmotion.HAPPY]
            ... )
            >>> audio = client.text_to_speech(
            ...     text="我很抱歉",
            ...     emotions=[BasicEmotion.SAD, ToneMarker.WHISPERING]
            ... )
            >>> audio = client.text_to_speech(
            ...     text="紧急通知！",
            ...     model=FishAudioModel.S1,
            ...     emotions=[ToneMarker.IN_A_HURRY]
            ... )
        """
        # 使用配置中的默认语音 ID，如果没有传入 reference_id
        voice_id = reference_id or settings.FISH_AUDIO_DEFAULT_VOICE_ID
        
        # 截取文本预览用于日志（最多50字符）
        text_preview = text[:50] + "..." if len(text) > 50 else text
        
        # 记录情绪标签
        if emotions:
            emotion_values = [e.value if isinstance(e, Enum) else e for e in emotions]
            logger.info(f"开始 TTS 转换，文本长度: {len(text)}，语音模型: {voice_id}，情绪标签: {emotion_values}")
        else:
            logger.info(f"开始 TTS 转换，文本长度: {len(text)}，语音模型: {voice_id}")
        
        logger.debug(f"TTS 转换文本内容: {text}")
        
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
                        latency=latency,
                        speed=speed,
                        emotions=emotions,
                        model=model
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
        latency: Literal["normal", "balanced"] = "normal",
        speed: Optional[float] = None,
        emotions: Optional[List[Union[str, Enum]]] = None,
        model: FishAudioModel = None
    ) -> str:
        """
        文本转语音并保存到文件
        
        Args:
            text: 要转换的文本
            output_path: 输出文件路径，不传则自动生成
            reference_id: 语音模型 ID
            format: 音频格式
            latency: 延迟模式
            speed: 语速参数，浮点数，通常范围 0.5-2.0
            emotions: 情绪标签列表，用于控制语音情感表达
            model: TTS 模型，可选 s1, speech-1.6, speech-1.5
            
        Returns:
            保存的文件路径
        """
        try:
            audio = self.text_to_speech(
                text=text,
                reference_id=reference_id,
                format=format,
                latency=latency,
                speed=speed,
                emotions=emotions,
                model=model
            )
            
            if output_path is None:
                app_dir = Path(__file__).parent.parent.parent
                audio_dir = app_dir / "audio_output"
                audio_dir.mkdir(exist_ok=True)
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                output_path = str(audio_dir / f"tts_{timestamp}.{format}")
            
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
        latency: Literal["normal", "balanced"] = "normal",
        speed: Optional[float] = None,
        emotions: Optional[List[Union[str, Enum]]] = None,
        model: FishAudioModel = None
    ) -> bytes:
        """
        文本转语音并返回字节数据（带超时和重试机制）
        
        Args:
            text: 要转换的文本
            reference_id: 语音模型 ID
            format: 音频格式
            latency: 延迟模式
            speed: 语速参数，浮点数，通常范围 0.5-2.0
            emotions: 情绪标签列表，用于控制语音情感表达
            model: TTS 模型，可选 s1, speech-1.6, speech-1.5
            
        Returns:
            音频字节数据
        """
        text_preview = text[:50] + "..." if len(text) > 50 else text
        
        try:
            audio_bytes = self.text_to_speech(
                text=text,
                reference_id=reference_id,
                format=format,
                latency=latency,
                speed=speed,
                emotions=emotions,
                model=model
            )
            
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

