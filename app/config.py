from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration. DATABASE_URL is the only integration seam — re-point it to
    S1's managed Postgres at merge time and nothing else changes."""

    database_url: str = "postgresql+psycopg://bazaar:bazaar@localhost:5433/bazaar"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
