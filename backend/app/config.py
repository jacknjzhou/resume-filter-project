from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://resume:resume@db:5432/resume_review"
    llm_base_url: str = "http://localhost:8000/v1"
    llm_api_key: str = "EMPTY"
    llm_model: str = "qwen2.5-72b-instruct"
    llm_vlm_model: str = ""
    llm_timeout: float = 120
    ocr_confidence_threshold: float = 0.85
    ocr_base_url: str = "http://ocr:8866"
    step_timeout: int = 120
    screening_pass_ratio: float = 0.4  # 初筛通过阈值：满足硬性要求条数占比
    max_concurrency: int = 3
    uploads_dir: str = "./uploads"

    model_config = SettingsConfigDict(env_file=".env")


@lru_cache
def get_settings() -> Settings:
    return Settings()
