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
    IMAGE_MODEL_NAME: str = ""
    
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
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
