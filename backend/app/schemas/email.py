"""
Email integration API schemas.

Response models are explicit allow-lists: no credential field (password,
app password, encrypted blob, decrypted secret) exists on any of them, so a
credential cannot be serialised by accident.
"""
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.schemas.job import JobStatus


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
class EmailConnectRequest(BaseModel):
    provider: Literal["gmail", "imap"]
    email: str = Field(..., min_length=3, max_length=320)
    password: SecretStr                      # masked in repr/logs; never echoed back
    host: Optional[str] = Field(None, max_length=253)

    @field_validator("password")
    @classmethod
    def _password_bounds(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if not raw or not raw.strip():
            raise ValueError("App password is required")
        if len(raw) > 512:
            raise ValueError("App password is too long")
        return v


class EmailSyncRequest(BaseModel):
    days_back: Optional[int] = Field(None, ge=1, le=365)
    max_messages: Optional[int] = Field(None, ge=1, le=1000)


class EmailDisconnectRequest(BaseModel):
    delete_imported_emails: bool = False


class SuggestionAcceptRequest(BaseModel):
    """User-reviewed values. For new_job suggestions these become the job."""
    model_config = ConfigDict(use_enum_values=True)

    company: Optional[str] = Field(None, max_length=200)
    position: Optional[str] = Field(None, max_length=200)
    status: Optional[JobStatus] = None
    job_url: Optional[str] = Field(None, max_length=500)
    salary_min: Optional[int] = Field(None, ge=0)
    salary_max: Optional[int] = Field(None, ge=0)
    location: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=1800)
    applied_date: Optional[str] = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
class ProviderInfo(BaseModel):
    id: str
    name: str
    fixed_host: Optional[str] = None
    requires_host: bool


class SyncLimits(BaseModel):
    default_days: int
    max_days: int
    default_messages: int
    max_messages: int
    cooldown_seconds: int


class SyncState(BaseModel):
    in_progress: bool
    last_sync_at: Optional[str] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_scanned: int = 0
    last_new_messages: int = 0
    last_job_related: int = 0
    last_new_suggestions: int = 0
    cooldown_seconds_remaining: int = 0


class EmailStatusResponse(BaseModel):
    state: Literal["not_connected", "connected", "needs_attention", "legacy_reconnect"]
    connected: bool
    provider: Optional[str] = None
    provider_name: Optional[str] = None
    email: Optional[str] = None
    host: Optional[str] = None
    status_detail: Optional[str] = None
    connected_at: Optional[str] = None
    last_verified_at: Optional[str] = None
    sync: Optional[SyncState] = None
    pending_suggestions: int = 0
    ai_enabled: bool = False
    providers: list[ProviderInfo]
    limits: SyncLimits


class ConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    code: Optional[str] = None
    status: EmailStatusResponse


class SyncSummaryOut(BaseModel):
    status: str
    scanned: int
    new_messages: int
    skipped_duplicates: int
    job_related: int
    new_suggestions: int
    updated_suggestions: int
    errors: int
    ai_used: int
    message: str


class SyncResponse(BaseModel):
    summary: SyncSummaryOut
    status: EmailStatusResponse


class SuggestionRef(BaseModel):
    id: int
    kind: str
    review_status: str
    status: str


class EmailMessageOut(BaseModel):
    id: int
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    subject: Optional[str] = None
    snippet: Optional[str] = None
    received_at: Optional[str] = None
    category: str
    confidence: Optional[float] = None
    classification_method: Optional[str] = None
    processing_status: str
    suggestion: Optional[SuggestionRef] = None


class EmailMessageDetail(EmailMessageOut):
    body_text: Optional[str] = None      # plain text only — render as text, never as HTML


class EmailMessageList(BaseModel):
    data: list[EmailMessageOut]
    total: int
    page: int
    limit: int
    pages: int


class MatchedJob(BaseModel):
    id: int
    company: str
    position: str
    status: str


class SuggestionEmail(BaseModel):
    id: int
    subject: Optional[str] = None
    sender_name: Optional[str] = None
    sender_email: Optional[str] = None
    received_at: Optional[str] = None
    snippet: Optional[str] = None


class SuggestionOut(BaseModel):
    id: int
    kind: Literal["new_job", "status_update"]
    company: Optional[str] = None
    position: Optional[str] = None
    status: str
    location: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    job_url: Optional[str] = None
    applied_date: Optional[str] = None
    category: str
    confidence: float
    extraction_method: str
    review_status: str
    created_job_id: Optional[int] = None
    matched_job: Optional[MatchedJob] = None
    email: Optional[SuggestionEmail] = None
    created_at: Optional[str] = None


class SuggestionList(BaseModel):
    data: list[SuggestionOut]
    total: int
