from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PLUGLAYER_API_BASE_URL: str = "https://api.pluglayer.com"
    PLUGLAYER_API_URL: str = Field(default="")  # legacy fallback
    PLUGLAYER_API_KEY: str = ""  # Set by user via env var
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8001
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def resolved_api_base_url(self) -> str:
        candidate = (self.PLUGLAYER_API_BASE_URL or "").strip() or (self.PLUGLAYER_API_URL or "").strip()
        return candidate or "https://api.pluglayer.com"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
