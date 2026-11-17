
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Reliable Webhook Delivery Engine"

    webhook_encryption_key: str | None = None

    database_url: str
    redis_url: str = "redis://127.0.0.1:6379/0"

    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Authentication rate limits
    login_max_attempts: int = 5
    login_window_seconds: int = 900

    registration_max_attempts: int = 5
    registration_window_seconds: int = 3600

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )




settings = Settings()
