from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str
    MASTER_BOT_TOKEN: str
    BOT_POLL_INTERVAL: int = 5
    PLATFORM_ADMIN_IDS: str = ""  # через запятую: "111,222"

    @property
    def platform_admin_ids(self) -> set[int]:
        return {int(x) for x in self.PLATFORM_ADMIN_IDS.split(",") if x.strip().isdigit()}


settings = Settings()
