from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PharmaIntelligence API"
    api_cors_origins: str = "http://localhost:3000"
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_secret_key: str = ""
    database_url: str = ""
    database_url_rls: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [part.strip() for part in self.api_cors_origins.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
