from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    PLUGLAYER_API_URL: str = "https://api.pluglayer.com"
    PLUGLAYER_API_KEY: str = ""  # Set by user via env var
    MCP_HOST: str = "0.0.0.0"
    MCP_PORT: int = 8001
    DEBUG: bool = False

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
