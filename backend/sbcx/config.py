"""Application settings. Every value can be set with an SBCX_* environment variable or in
backend/.env. OPENROUTER_API_KEY is also read from the repo-root .env used by the labeling
scripts, so one key serves both."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SBCX_",
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # storage
    var_dir: Path = BACKEND_DIR / "var"
    database_url: str = ""  # default: sqlite file under var_dir
    data_dir: Path = REPO_ROOT / "data"
    config_dir: Path = BACKEND_DIR / "config"

    # uploads
    max_upload_mb: int = 10
    max_pages: int = 20

    # LLM (OpenRouter)
    openrouter_api_key: str | None = Field(default=None, validation_alias="OPENROUTER_API_KEY")
    llm_mode: Literal["openrouter", "fake", "off"] = "openrouter"
    model_fallback: str = "deepseek/deepseek-v4-flash"
    model_summary: str = "deepseek/deepseek-v4-flash"
    model_explanation: str = "deepseek/deepseek-v4-flash"
    llm_timeout_s: float = 90.0
    llm_budget_usd: float = 2.0  # per process; calls stop once spent

    # extraction
    fallback_enabled: bool = True
    confidence_threshold: float = 0.75  # calibrated on v1.4 reviewed (roadmap M6)
    summaries_enabled: bool = True

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{self.var_dir / 'sbcx.db'}"

    @property
    def llm_available(self) -> bool:
        return self.llm_mode == "fake" or (self.llm_mode == "openrouter" and bool(self.openrouter_api_key))


@lru_cache
def get_settings() -> Settings:
    return Settings()
