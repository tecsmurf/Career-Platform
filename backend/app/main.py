"""
AI Career Platform — Main Application
======================================
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
from app.core.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: create tables if they don't exist
    await init_db()
    yield
    # Shutdown: cleanup (nothing needed for now)


app = FastAPI(
    title="AI Career Platform",
    description="Track your job applications, powered by AI",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: prefer an explicit allow-list of exact origins (set ALLOWED_ORIGINS in
# the environment). Fall back to the origin regex when none is configured so
# existing dev/preview deployments keep working.
cors_kwargs = dict(
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if settings.cors_origins:
    cors_kwargs["allow_origins"] = settings.cors_origins
else:
    cors_kwargs["allow_origin_regex"] = settings.ALLOWED_ORIGIN_REGEX

app.add_middleware(CORSMiddleware, **cors_kwargs)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "app": "AI Career Platform",
        "version": "1.0.0",
        "docs": "/docs",
    }
