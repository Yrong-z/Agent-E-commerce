"""读取根目录本地配置，密钥不进入响应或日志。"""
from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    """后端配置；聊天和向量模型分别配置。"""
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / '.env', env_file_encoding='utf-8', env_ignore_empty=True, extra='ignore')
    database_url: SecretStr = SecretStr('postgresql://shopping:shopping_demo_local@127.0.0.1:5433/shopping')
    chat_base_url: str = ''
    chat_api_key: SecretStr = SecretStr('')
    chat_model: str = ''
    embedding_base_url: str = 'http://127.0.0.1:8082/v1'
    embedding_api_key: SecretStr = SecretStr('')
    embedding_model: str = 'bge-large-zh-v1.5'
    embedding_dimension: int | None = Field(default=None, gt=0)
    app_mode: str = 'demo'
    demo_customer_id: str = 'demo-user'
    serve_frontend: bool = False

@lru_cache
def get_settings() -> Settings:
    """获取经过校验的配置。"""
    return Settings()
