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


async def _call_email_mcp_server(days_back: int, max_emails: int) -> dict:
    """
    Connect to the Email MCP Server and call scan_job_emails.
    
    This demonstrates the MCP client-server pattern:
    1. Start the MCP server as a subprocess
    2. Initialize the MCP session
    3. Call a tool by name
    4. Get the result
    5. Disconnect
    """
    server_params = StdioServerParameters(
        command="python",
        args=["mcp_servers/email_reader/server.py"],
        env={
            "EMAIL_HOST": settings.EMAIL_HOST,
            "EMAIL_USER": settings.EMAIL_USER,
            "EMAIL_PASSWORD": settings.EMAIL_PASSWORD,
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
    
    This:
    1. Connects to your email via the Email MCP Server
    2. Scans for job-related emails (interviews, offers, rejections)
    3. Matches emails to your jobs in the database
    4. Updates job statuses automatically
    
    Only forward progressions are applied (applied → interviewing → offer).
    Rejected/withdrawn are terminal states.
    """
    try:
        # Step 1: Call Email MCP Server
        scan_result = await _call_email_mcp_server(req.days_back, req.max_emails)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to connect to email: {str(e)}. Make sure EMAIL_USER and EMAIL_PASSWORD are set in .env",
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
    
    Use this to verify before running the actual sync.
    """
    try:
        scan_result = await _call_email_mcp_server(req.days_back, req.max_emails)
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
