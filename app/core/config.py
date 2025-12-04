from typing import Any, Dict, List, Optional, Union
from pydantic import AnyHttpUrl, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 应用基础配置
    APP_NAME: str = "Video Generator API"
    APP_VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    
    # 安全配置
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24小时
    
    # CORS配置
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []
    ALLOWED_HOSTS: List[str] = ["*"]
    
    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    # 数据库配置
    DATABASE_HOST: str
    DATABASE_PORT: int = 5432
    DATABASE_USER: str
    DATABASE_PASSWORD: str
    DATABASE_NAME: str
    DATABASE_URL: Optional[PostgresDsn] = None
    
    @model_validator(mode="after")
    def assemble_db_connection(self) -> "Settings":
        if self.DATABASE_URL is None:
            self.DATABASE_URL = PostgresDsn.build(
                scheme="postgresql",
                username=self.DATABASE_USER,
                password=self.DATABASE_PASSWORD,
                host=self.DATABASE_HOST,
                port=self.DATABASE_PORT,
                path=self.DATABASE_NAME,
            )
        return self
    
    # Redis配置
    # Redis 数据库编号说明：
    # - /0: 数据库0（默认数据库）
    # - /1: 数据库1
    # - Redis 默认有 16 个数据库（0-15）
    # - 不同数据库之间数据完全隔离
    REDIS_URL: str = "redis://localhost:6379/0"  # 通用 Redis URL（向后兼容）
    REDIS_BROKER_URL: str = "redis://localhost:6379/0"  # Celery Broker（任务队列）
    REDIS_BACKEND_URL: str = "redis://localhost:6379/1"  # Celery Backend（结果存储）
    
    # 文件上传配置
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE: int = 100 * 1024 * 1024  # 100MB
    
    # AI服务配置
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    LLM_MODEL_NAME: str = ""
    # 图片生成模型配置
    IMAGE_MODEL_TEXT_TO_IMAGE: str = ""  # 文生图模型（用于生成角色图片）
    IMAGE_MODEL_IMAGE_TO_IMAGE: str = ""  # 图生图模型（用于生成分镜图片）
    # 向后兼容：如果新配置未设置，使用旧配置
    IMAGE_MODEL_NAME: str = ""  # 旧配置（已废弃，保留用于向后兼容）
    
    # AI 重试配置
    AI_MAX_RETRIES: int = 3  # 最大重试次数
    AI_TIMEOUT: int = 120  # 超时时间（秒）
    AI_RETRY_DELAY: int = 2  # 重试间隔（秒）
    
    # 云存储配置 (US3)
    US3_PUBLIC_KEY: str = ""
    US3_PRIVATE_KEY: str = ""
    US3_BUCKET: str = ""  # US3 存储桶名称
    US3_REGION: str = ""  # US3 区域
    DOWNLOAD_SUFFIX: str = ""
    UPLOAD_SUFFIX: str = ""
    DEFAULT_BUCKET: str = ""
    
    # Fish Audio 配置
    FISH_AUDIO_API_KEY: str = ""
    FISH_AUDIO_DEFAULT_VOICE_ID: str = ""  # 默认语音模型 ID，如 "54a5170264694bfc8e9ad98df7bd89c3" (丁真)
    
    # 字体配置
    FONT_DIR: str = "static/fonts"  # 字体文件本地存储目录
    SUBTITLE_FONT_URL: str = "https://novel-agent.cn-sh2.ufileos.com/font/black.ttf"  # 字幕字体下载地址
    SUBTITLE_FONT_NAME: str = "black.ttf"  # 字幕字体文件名
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    
    # 积分系统配置
    # 注册赠送
    POINTS_REGISTER_REWARD: int = 100  # 注册赠送积分
    
    # 每日签到
    POINTS_CHECKIN_REWARD: int = 10  # 每日签到积分
    POINTS_CHECKIN_EXPIRE_HOURS: int = 0  # 签到积分过期时间（小时），0表示当天24:00过期
    
    # 积分消耗配置（支持多种计费方式，通过配置字符串定义）
    # 格式：operation_type:计费方式:数值
    # 计费方式：per_unit（按单位）、per_second（按秒）、per_word（按字数）、per_cost（按实际成本）
    POINTS_CREATE_CREATION: str = "create_creation:per_unit:10"  # 创建创作：10积分/次
    POINTS_GENERATE_CHARACTER: str = "generate_character:per_unit:5"  # 生成角色：5积分/个
    POINTS_GENERATE_SHOT: str = "generate_shot:per_unit:3"  # 生成分镜：3积分/个
    POINTS_GENERATE_AUDIO: str = "generate_audio:per_second:1"  # 生成音频：1积分/秒
    POINTS_GENERATE_VIDEO: str = "generate_video:per_shot:2"  # 生成视频：2积分/片段
    POINTS_UPLOAD_NOVEL: str = "upload_novel:per_unit:5"  # 上传小说：5积分/次
    POINTS_LLM_CALL: str = "llm_call:per_cost:100"  # 大模型调用：按实际成本，100积分=1元（即1积分=0.01元）
    
    # 模型价格配置（JSON格式字符串）
    MODEL_PRICES_LLM: str = '{"Qwen/Qwen-Plus": {"input": 0.8, "output": 2.0}}'  # LLM模型价格：输入/输出价格（元/百万tokens）
    MODEL_PRICES_IMAGE: str = '{"black-forest-labs/flux-kontext-pro/multi": 0.35}'  # 图片模型价格：元/张
    MODEL_PRICES_AUDIO: str = '{"s1": 120}'  # 音频模型价格：元/兆字节
    
    ENABLE_TEST_EXCEPTION: str = "false"
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
