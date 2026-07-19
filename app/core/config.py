from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Science Olympiad Learning Platform"
    environment: str = "development"
    database_url: str = "sqlite:///./science_olympiad.db"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 120
    auth_provider: str = "local"
    firebase_project_id: str | None = None
    firebase_web_api_key: str | None = None
    firebase_check_revoked: bool = True
    allowed_crawl_domains: str = "nasa.gov,noaa.gov,usgs.gov,nih.gov,cdc.gov,epa.gov,nist.gov"
    crawl_max_bytes: int = 5_000_000
    artifact_store_path: str = "./data/artifacts"
    openai_compatible_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    redis_url: str | None = None
    worker_poll_seconds: float = 2.0
    crawl_scheduler_minutes: int = 15
    email_delivery_provider: str = "disabled"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    public_app_url: str = "http://localhost:8000"
    tutor_daily_messages: int = 50
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def crawl_allowlist(self) -> set[str]:
        return {d.strip().lower() for d in self.allowed_crawl_domains.split(",") if d.strip()}

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.auth_provider not in {"local", "firebase"}:
            raise ValueError("AUTH_PROVIDER must be either local or firebase")
        if self.environment.lower() == "production" and self.auth_provider != "firebase":
            raise ValueError("AUTH_PROVIDER=firebase is required in production")
        if self.environment.lower() == "production" and not self.artifact_store_path:
            raise ValueError("ARTIFACT_STORE_PATH is required in production")
        if self.auth_provider == "firebase" and not self.firebase_project_id:
            raise ValueError("FIREBASE_PROJECT_ID is required when Firebase authentication is enabled")
        if self.auth_provider == "firebase" and not self.firebase_web_api_key:
            raise ValueError("FIREBASE_WEB_API_KEY is required when Firebase authentication is enabled")
        if self.environment.lower() == "production" and self.auth_provider == "local" and self.jwt_secret == "change-me-in-production":
            raise ValueError("JWT_SECRET must be explicitly configured in production")
        if self.environment.lower() == "production" and self.auth_provider == "local" and len(self.jwt_secret) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters in production")
        if self.email_delivery_provider not in {"disabled", "smtp"}:
            raise ValueError("EMAIL_DELIVERY_PROVIDER must be disabled or smtp")
        if self.environment.lower() == "production" and self.email_delivery_provider != "smtp":
            raise ValueError("EMAIL_DELIVERY_PROVIDER=smtp is required in production")
        if self.email_delivery_provider == "smtp" and not all((self.smtp_host, self.smtp_from_email)):
            raise ValueError("SMTP_HOST and SMTP_FROM_EMAIL are required for SMTP delivery")
        if self.smtp_username and not self.smtp_password:
            raise ValueError("SMTP_PASSWORD is required when SMTP_USERNAME is configured")
        if self.environment.lower() == "production" and not self.public_app_url.startswith("https://"):
            raise ValueError("PUBLIC_APP_URL must use HTTPS in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
