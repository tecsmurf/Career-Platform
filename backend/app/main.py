"""
AI Career Platform — Main Application
======================================
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router as api_router
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://career-platform-rho.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "app": "AI Career Platform",
        "version": "1.0.0",
        "docs": "/docs",
    }
