from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_path: str = "health_monitor.sqlite3"
    sites_config_path: str = "sites.json"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    daily_summary_timezone: str = "UTC"
    daily_summary_time: str = "18:00"
    heartbeat_timeout_seconds: int = 90
    heartbeat_poll_seconds: int = 5
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    debug_logging: bool = True


settings = Settings()
