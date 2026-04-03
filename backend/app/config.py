"""应用配置"""
import os
from pydantic_settings import BaseSettings
from typing import Optional


def _is_remote_uri(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "智慧党建助手"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # 数据库配置（默认SQLite，无需安装MySQL即可运行）
    DATABASE_URL: str = "sqlite:///./party_brain.db"

    # Redis配置
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT配置（总系统统一认证）
    SECRET_KEY: str = "7b4c9e2a8f1d6c3b5e9a2f8c7b4d9e6a3f1b8c7d5e9a2f8c7b4d9e6a3f1b8c"
    ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "gov-backend"
    JWT_AUDIENCE: str = "gov-platform"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8小时

    # LLM配置
    LLM_BASE_URL: str = "http://192.168.1.100:18888/v1"
    LLM_API_KEY: str = "gpustack_cd9723bca82e5e9e_a9b7da5f0badf8ad9568d5275624847c"
    LLM_MODEL: str = "DeepSeek-R1"
    LLM_MAX_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.7

    # Embedding配置（总系统本地模型）
    EMBEDDING_BASE_URL: str = "http://192.168.1.100:40086/v1"
    EMBEDDING_API_KEY: str = "not-needed"
    EMBEDDING_MODEL: str = "bge-m3"

    # 工具调用模式
    # "native"   = 使用模型原生 Function Calling（OpenAI 兼容）
    # "prompt"   = 使用 Prompt 模拟 ReAct（兼容所有模型，但依赖模型遵循格式）
    # "workflow"  = 使用 Workflow 工作流驱动（最稳定，适合弱模型）
    TOOL_CALL_MODE: str = "workflow"

    # Milvus 配置
    # 本地测试: "./milvus_data.db"（Milvus Lite 文件模式）
    # 远程部署: "http://127.0.0.1:19530"（连接总系统 Milvus）
    MILVUS_URI: str = "http://127.0.0.1:19530"
    MILVUS_HOST: Optional[str] = None
    MILVUS_PORT: Optional[int] = None
    MILVUS_COLLECTION: str = "party_committee"

    # 文件存储
    UPLOAD_DIR: str = "./uploads"
    EXPORT_DIR: str = "./exports"

    @property
    def effective_milvus_uri(self) -> str:
        uri = (self.MILVUS_URI or "").strip()
        host = (self.MILVUS_HOST or "").strip()
        port = self.MILVUS_PORT or 19530
        if host and (not uri or not _is_remote_uri(uri)):
            return f"http://{host}:{port}"
        return uri

    @property
    def milvus_mode(self) -> str:
        return "remote" if _is_remote_uri(self.effective_milvus_uri) else "local"

    @property
    def milvus_runtime_info(self) -> dict:
        return {
            "mode": self.milvus_mode,
            "effective_uri": self.effective_milvus_uri,
            "settings_milvus_uri": self.MILVUS_URI,
            "settings_milvus_host": self.MILVUS_HOST,
            "settings_milvus_port": self.MILVUS_PORT,
            "collection": self.MILVUS_COLLECTION,
            "env_milvus_uri": os.getenv("MILVUS_URI", ""),
            "env_milvus_host": os.getenv("MILVUS_HOST", ""),
            "env_milvus_port": os.getenv("MILVUS_PORT", ""),
        }

    @property
    def embedding_runtime_info(self) -> dict:
        return {
            "base_url": self.EMBEDDING_BASE_URL,
            "model": self.EMBEDDING_MODEL,
            "settings_embedding_base_url": self.EMBEDDING_BASE_URL,
            "settings_embedding_model": self.EMBEDDING_MODEL,
            "env_embedding_base_url": os.getenv("EMBEDDING_BASE_URL", ""),
            "env_embedding_model": os.getenv("EMBEDDING_MODEL", ""),
        }

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
