from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PLUGLAYER_API_URL: str = Field(default="")
    PLUGLAYER_API_KEY: str = ""  # Set by user via env var
    MCP_HOST: str = "127.0.0.1"
    MCP_PORT: int = 0
    DEBUG: bool = False

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def resolved_api_base_url(self) -> str:
        candidate = (self.PLUGLAYER_API_URL or "").strip()
        return candidate or "https://api.pluglayer.com"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
