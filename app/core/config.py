from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip_surrounding_quotes(value: str) -> str:
    """Render / copy-paste often includes wrapping quotes in the value; browsers never send those."""
    s = value.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1].strip()
    return s


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

    r2_endpoint_url: str = ""
    r2_bucket_name: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""

    @property
    def r2_enabled(self) -> bool:
        return bool(
            self.r2_endpoint_url.strip()
            and self.r2_bucket_name.strip()
            and self.r2_access_key_id.strip()
            and self.r2_secret_access_key.strip()
        )

    @field_validator("database_url", "cors_origins", "public_base_url", "r2_endpoint_url", mode="before")
    @classmethod
    def strip_wrapping_quotes(cls, v: object) -> object:
        if isinstance(v, str):
            return _strip_surrounding_quotes(v)
        return v


settings = Settings()
