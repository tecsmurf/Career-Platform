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

    # ---------------------------------------------------------------
    # Email integration
    # ---------------------------------------------------------------
    # Fernet key(s) used to encrypt stored mailbox credentials. Comma-separated;
    # the FIRST key encrypts, all keys can decrypt (allows rotation). Generate:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # If empty, a key is derived from SECRET_KEY (works, but rotating SECRET_KEY
    # will then require users to reconnect their email).
    EMAIL_ENCRYPTION_KEY: str = ""

    EMAIL_IMAP_TIMEOUT_SECONDS: int = 15        # connect / login / per-command socket timeout
    EMAIL_SYNC_MAILBOX: str = "INBOX"
    EMAIL_SYNC_DEFAULT_DAYS: int = 30
    EMAIL_SYNC_MAX_DAYS: int = 90
    EMAIL_SYNC_DEFAULT_MESSAGES: int = 50
    EMAIL_SYNC_MAX_MESSAGES: int = 100         # hard cap per sync
    EMAIL_SYNC_MAX_BODY_BYTES: int = 131072    # only the first 128 KB of a message is downloaded
    EMAIL_SYNC_TIME_BUDGET_SECONDS: int = 45   # sync stops (partial) when exceeded
    EMAIL_SYNC_COOLDOWN_SECONDS: int = 60      # min seconds between syncs per user
    EMAIL_SYNC_LOCK_SECONDS: int = 300         # stale-lock expiry if a sync process dies
    EMAIL_CONNECT_MAX_ATTEMPTS: int = 5        # connect attempts per window per user
    EMAIL_TEST_MAX_ATTEMPTS: int = 10          # connection tests per window per user
    EMAIL_RATE_WINDOW_SECONDS: int = 900
    EMAIL_AI_MAX_PER_SYNC: int = 20            # cap on LLM calls per sync (cost/abuse control)

    # OpenAI (optional — enables AI extraction; rule-based detection works without it)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TIMEOUT_SECONDS: int = 20

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.strip().lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def email_encryption_keys(self) -> list[str]:
        return [k.strip() for k in self.EMAIL_ENCRYPTION_KEY.split(",") if k.strip()]

    @model_validator(mode="after")
    def _enforce_security(self):
        # Fail fast on a malformed encryption key (never echo the key itself).
        if self.email_encryption_keys:
            from cryptography.fernet import Fernet
            for i, key in enumerate(self.email_encryption_keys):
                try:
                    Fernet(key.encode())
                except Exception:
                    raise ValueError(
                        f"EMAIL_ENCRYPTION_KEY entry #{i + 1} is not a valid Fernet key "
                        "(expected 32 url-safe base64-encoded bytes)."
                    ) from None
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
