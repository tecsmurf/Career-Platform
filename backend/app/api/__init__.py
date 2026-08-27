"""
API Router — Central hub for all API routes
============================================

This file collects all route modules and bundles them under one router.
main.py includes this router with prefix="/api", so:

    health routes  → /api/health
    auth routes    → /api/auth/login, /api/auth/register
    job routes     → /api/jobs, /api/jobs/{id}

Think of this as the "table of contents" for your API.
"""
from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.jobs import router as jobs_router
from app.api.email_sync import router as email_router

router = APIRouter()

# Mount sub-routers
router.include_router(health_router, tags=["Health"])
router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
router.include_router(jobs_router, prefix="/jobs", tags=["Jobs"])
router.include_router(email_router, prefix="/email", tags=["Email Sync"])
