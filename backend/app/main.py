"""
AI Career Platform — Main Application
======================================
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router as api_router
from app.core.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: create tables if they don't exist
    await init_db()
    if settings.email_auth_active and not settings.login_ip_limit_active:
        logging.getLogger("app.security").warning(
            "Account email is on but per-IP limits are off (no CLIENT_IP_HEADER). Sign-up and reset "
            "emails are then limited only per account and by the daily quota; set CLIENT_IP_HEADER "
            "(e.g. CF-Connecting-IP) to enable per-IP limits."
        )
    yield
    # Shutdown: cleanup (nothing needed for now)


app = FastAPI(
    title="AI Career Platform",
    description="Track your job applications, powered by AI",
    version="1.0.0",
    lifespan=lifespan,
)

class ApplyBodyLimit:
    """Cap request bodies for /api/apply/* before they are parsed or spooled.

    6 MB for resume uploads (5 MB file + multipart overhead), 1 MB for every
    other Apply Assistant request. Checks Content-Length up front and counts
    streamed bytes, so chunked uploads are cut off too.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if not path.startswith("/api/apply"):
            return await self.app(scope, receive, send)
        limit = 6 * 1024 * 1024 if path.endswith("/resume/upload") else 1024 * 1024
        for name, value in scope.get("headers", []):
            if name == b"content-length" and value.isdigit() and int(value) > limit:
                return await self._too_large(send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._too_large(send)

    @staticmethod
    async def _too_large(send):
        body = b'{"detail":{"code":"too_large","message":"That request is too large."}}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass



# Inner to CORS, so even a 413 carries CORS headers the browser can read.
app.add_middleware(ApplyBodyLimit)

# CORS: prefer an explicit allow-list of exact origins (set ALLOWED_ORIGINS in
# the environment). Fall back to the origin regex when none is configured so
# existing dev/preview deployments keep working.
cors_kwargs = dict(
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Retry-After is not a CORS-safelisted header: without this the browser
    # hides it from the (cross-origin) frontend on 429 responses.
    expose_headers=["Retry-After"],
)
if settings.cors_origins:
    cors_kwargs["allow_origins"] = settings.cors_origins
else:
    cors_kwargs["allow_origin_regex"] = settings.ALLOWED_ORIGIN_REGEX

app.add_middleware(CORSMiddleware, **cors_kwargs)



_SENSITIVE_LOC = ("password", "secret", "credential", "token")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Same shape as FastAPI's default 422, but never echoes submitted values.

    The default handler includes each failing field's raw `input` — for a
    malformed connect request that could reflect a mailbox password back.
    """
    errors = []
    for err in exc.errors():
        e = {k: v for k, v in err.items() if k != "input"}
        loc = " ".join(str(part) for part in e.get("loc", ())).lower()
        if any(word in loc for word in _SENSITIVE_LOC):
            e.pop("ctx", None)
        errors.append(e)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "app": "AI Career Platform",
        "version": "1.0.0",
        "docs": "/docs",
    }
