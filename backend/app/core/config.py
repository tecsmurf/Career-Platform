"""
Application Configuration
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "AI Career Platform"
    DEBUG: bool = True

    # Auth
    SECRET_KEY: str = "dev-secret-key-change-in-production-abc123xyz"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/career_platform"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Email (Gmail IMAP — requires App Password)
    EMAIL_HOST: str = "imap.gmail.com"
    EMAIL_USER: str = ""       # your-email@gmail.com
    EMAIL_PASSWORD: str = ""   # Gmail App Password (not your regular password)

    # OpenAI (for AI-powered job matching from emails)
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()
