"""
Health Check Endpoint
=====================

Every production API needs a health check. Load balancers, monitoring tools,
and Docker all use this to know "is the app alive?"

    GET /api/health → 200 OK = app is running
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Check if the API is running."""
    return {
        "status": "healthy",
        "service": "AI Career Platform",
    }
