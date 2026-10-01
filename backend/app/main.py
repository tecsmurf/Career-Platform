"""
AI Career Platform — Main Application
======================================
"""
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
