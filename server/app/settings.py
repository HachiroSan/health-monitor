from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_path: str = "health_monitor.sqlite3"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    daily_summary_timezone: str = "Asia/Kuala_Lumpur"
    daily_summary_time: str = "18:00"
    heartbeat_timeout_seconds: int = 30
    heartbeat_poll_seconds: int = 5
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


settings = Settings()
