from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Alert Hub"
    api_prefix: str = "/api"
    database_url: str
    secret_key: str
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    cors_origins: str = "http://localhost:5173"
    # If true: Access-Control-Allow-Origin: * and no credentialed CORS (fine for this app’s Bearer tokens in
    # memory/localStorage; do not use with cookie-based sessions). Avoids chasing new frontend origins.
    cors_allow_any_origin: bool = False

    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_claims_sub: str = "mailto:admin@example.com"

    telegram_api_id: int | None = None
    telegram_api_hash: str = ""
    public_base_url: str = "http://localhost:8000"


settings = Settings()
