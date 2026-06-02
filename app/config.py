from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    db_url: str = "sqlite:///./data/drs.sqlite"

    # 32-Byte-Key (hex oder utf-8 32+ chars). Im Container aus /etc/drs/secret.key.
    secret_key: str = "dev-only-change-me-dev-only-change"

    # Cookie/Session
    session_cookie_name: str = "drs_session"
    session_max_age_days: int = 30

    # Lockout
    max_failed_attempts: int = 5
    lockout_minutes: int = 15

    bind_host: str = "127.0.0.1"
    bind_port: int = 8000


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
