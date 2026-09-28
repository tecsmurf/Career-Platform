"""
Application Configuration
=========================

Settings are loaded from environment variables (and a local .env in dev).

Security note:
    In production (ENVIRONMENT=production) a strong, unique SECRET_KEY MUST be
    supplied via the environment. The app refuses to start otherwise, so it can
    never silently fall back to a publicly-known signing key.
"""
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The old committed placeholder. Allowed only in local dev/test, never in prod.
INSECURE_DEFAULT_SECRET = "dev-secret-key-change-in-production-abc123xyz"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="allow")

    APP_NAME: str = "AI Career Platform"
    # "development" | "production". Set ENVIRONMENT=production on Render.
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Auth — MUST be provided via env in production (no insecure default there).
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/career_platform"

    # CORS — comma-separated exact origins (preferred in production, e.g.
    # "https://my-app.vercel.app,https://www.myapp.com"). When empty, falls back
    # to ALLOWED_ORIGIN_REGEX so existing deployments keep working.
    ALLOWED_ORIGINS: str = ""
    ALLOWED_ORIGIN_REGEX: str = r"https://.*\.vercel\.app|http://localhost:\d+"

    # Redis (reserved; not currently used)
    REDIS_URL: str = "redis://localhost:6379/0"

    # Email (Gmail IMAP — requires App Password)
    EMAIL_HOST: str = "imap.gmail.com"
    EMAIL_USER: str = ""       # your-email@gmail.com
    EMAIL_PASSWORD: str = ""   # Gmail App Password (not your regular password)

    # OpenAI (for AI-powered job matching from emails)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @model_validator(mode="after")
    def _enforce_security(self):
        if self.is_production:
            if not self.SECRET_KEY or self.SECRET_KEY == INSECURE_DEFAULT_SECRET:
                raise ValueError(
                    "SECRET_KEY must be set to a strong, unique value in production. "
                    "Set the SECRET_KEY environment variable (e.g. `openssl rand -hex 32`)."
                )
            if self.DEBUG:
                raise ValueError("DEBUG must be False in production.")
        else:
            # Local dev/test convenience only — never reached in production.
            if not self.SECRET_KEY:
                self.SECRET_KEY = INSECURE_DEFAULT_SECRET
        return self


settings = Settings()
