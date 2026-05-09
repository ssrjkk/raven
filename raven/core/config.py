from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    default_model: str = "openrouter/anthropic/claude-3-haiku"

    telegram_bot_token: str = ""
    discord_bot_token: str = ""
    slack_bot_token: str = ""
    slack_app_token: str = ""

    allowed_users: str = ""
    dm_policy: str = "pairing"

    db_path: str = "~/.raven/raven.db"
    vector_db_path: str = "~/.raven/chroma"

    web_port: int = 18888
    web_secret_key: str = "change-me-in-production"

    log_level: str = "INFO"
    log_file: str = "~/.raven/raven.log"

    @property
    def resolved_db_path(self) -> Path:
        return Path(self.db_path).expanduser()

    @property
    def resolved_vector_db_path(self) -> Path:
        return Path(self.vector_db_path).expanduser()

    @property
    def resolved_log_file(self) -> Path:
        return Path(self.log_file).expanduser()

    @property
    def parsed_allowed_users(self) -> dict[str, set[str]]:
        if not self.allowed_users:
            return {}
        result: dict[str, set[str]] = {}
        for entry in self.allowed_users.split(","):
            entry = entry.strip()
            if ":" in entry:
                channel, uid = entry.split(":", 1)
                result.setdefault(channel.strip(), set()).add(uid.strip())
        return result

    @property
    def data_dir(self) -> Path:
        return Path("~/.raven").expanduser()


settings = Settings()
