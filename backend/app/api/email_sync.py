"""
Email Sync Endpoints — Auto-update jobs from email
===================================================

POST /api/email/sync     → Scan emails, match to jobs, auto-update statuses
GET  /api/email/preview  → Preview what would be updated (dry run, no changes)

This connects the Email MCP Server to the Job database.
"""
import json
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.database import get_db
from app.models.models import User
from app.services.email_sync_service import auto_update_jobs_from_emails

# Import MCP client tools
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from app.core.config import settings

router = APIRouter()


class SyncRequest(BaseModel):
    days_back: int = Field(default=7, ge=1, le=90, description="How many days back to scan")
    max_emails: int = Field(default=50, ge=1, le=200, description="Max emails to scan")


class SyncResult(BaseModel):
    total_scanned: int
    job_emails_found: int
    updates_made: list[dict]
    message: str


async def _call_email_mcp_server(email_host: str, email_user: str, email_password: str, days_back: int, max_emails: int) -> dict:
    """
    Connect to the Email MCP Server and call scan_job_emails.
    
    Uses per-user credentials passed from the database.
    """
    server_params = StdioServerParameters(
        command="python",
        args=["mcp_servers/email_reader/server.py"],
        env={
            "EMAIL_HOST": email_host,
            "EMAIL_USER": email_user,
            "EMAIL_PASSWORD": email_password,
        },
    )
    
    async with stdio_client(server_params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            
            # Call the scan_job_emails tool via MCP protocol
            result = await session.call_tool(
                "scan_job_emails",
                {"days_back": days_back, "count": max_emails},
            )
            
            # Parse the result
            text_content = next(
                (c.text for c in result.content if hasattr(c, "text")),
                "{}"
            )
            return json.loads(text_content)


@router.post("/sync", response_model=SyncResult)
async def sync_emails(
    req: SyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Scan your email inbox for job-related updates and auto-update job statuses.
    
    Each user connects their own Gmail via Settings → Email Settings.
    """
    # Check if user has configured email
    if not current_user.has_email_configured:
        raise HTTPException(
            status_code=400,
            detail="Email not configured. Go to Settings → Email Settings to connect your Gmail.",
        )

    try:
        # Step 1: Call Email MCP Server with THIS user's credentials
        scan_result = await _call_email_mcp_server(
            email_host=current_user.email_host or "imap.gmail.com",
            email_user=current_user.email_user,
            email_password=current_user.email_app_password,
            days_back=req.days_back,
            max_emails=req.max_emails,
        )
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to email: {str(e)}. Check your email settings.",
        )
    
    job_emails = scan_result.get("job_emails", [])
    
    if not job_emails:
        return SyncResult(
            total_scanned=scan_result.get("total_scanned", 0),
            job_emails_found=0,
            updates_made=[],
            message="No job-related emails found in the scanned period.",
        )
    
    # Step 2: Match and update
    updates = await auto_update_jobs_from_emails(db, current_user.id, job_emails)
    
    return SyncResult(
        total_scanned=scan_result.get("total_scanned", 0),
        job_emails_found=len(job_emails),
        updates_made=updates,
        message=f"Found {len(job_emails)} job emails, made {len(updates)} status updates.",
    )


@router.post("/preview")
async def preview_sync(
    req: SyncRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Dry run — shows what WOULD be updated without making changes.
    """
    if not current_user.has_email_configured:
        raise HTTPException(400, "Email not configured. Go to Settings → Email Settings to connect your Gmail.")

    try:
        scan_result = await _call_email_mcp_server(
            email_host=current_user.email_host or "imap.gmail.com",
            email_user=current_user.email_user,
            email_password=current_user.email_app_password,
            days_back=req.days_back,
            max_emails=req.max_emails,
        )
    except Exception as e:
        raise HTTPException(503, f"Email connection failed: {str(e)}")
    
    job_emails = scan_result.get("job_emails", [])
    
    return {
        "total_scanned": scan_result.get("total_scanned", 0),
        "job_emails_found": len(job_emails),
        "detected_signals": [
            {
                "subject": e.get("subject"),
                "from": e.get("from"),
                "detected_company": e.get("detected_company"),
                "detected_status": e.get("job_signal", {}).get("detected_status"),
                "confidence": e.get("job_signal", {}).get("confidence"),
            }
            for e in job_emails
        ],
        "message": "Preview only — no changes made. Use POST /api/email/sync to apply.",
    }

