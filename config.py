"""Application configuration from environment."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    admin_username: str = "admin"
    admin_password: str = "admin"
    secret_key: str = "dev-secret-change-me"
    bot_token: str = ""
    database_url: str = f"sqlite+aiosqlite:///{DATA_DIR / 'shop.db'}"
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
