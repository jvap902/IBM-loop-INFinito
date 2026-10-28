"""Telecom AI Platform — Tool API (Sub-Task 4).

FastAPI application entry point.

Startup
-------
    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

Environment variables
---------------------
TOOL_API_KEY     Single API key (legacy).
TOOL_API_KEYS    Comma-separated list of valid API keys (preferred).
GOLD_PARQUET_PATH  Path to the Gold Feature Store Parquet file.
LOG_LEVEL          Python logging level (default: INFO).
API_VERSION        Version string embedded in responses (default: 1.0.0).
"""
from __future__ import annotations

import logging
import logging.config
import os
import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.routes.tools import router as tools_router
from api.routes.audit import router as audit_router
from api.routes.agent import router as agent_router
from api.routes.chat import router as chat_router
from api.schemas import HealthResponse

# ── Structured JSON logging ────────────────────────────────────────────────

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "logging.Formatter",
            # Pseudo-JSON format — a proper JSON formatter (python-json-logger)
            # can replace this in production without changing the config key.
            "fmt": "%(asctime)s",
            "format": (
                '{"timestamp": "%(asctime)s", "level": "%(levelname)s", '
                '"logger": "%(name)s", "message": %(message)r}'
            ),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.FileHandler",
            "formatter": "json",
            "filename": os.getenv("LOG_FILE", "logs/api.log"),
            "encoding": "utf-8",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": _LOG_LEVEL,
    },
}

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# ── Application factory ────────────────────────────────────────────────────

API_VERSION = os.getenv("API_VERSION", "1.0.0")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Telecom AI Platform — Tool API",
        description=(
            "Internal REST API that exposes the three ML analytical pipelines "
            "(Axis 1: Maintenance & Criticality, Axis 2: Expansion Opportunities, "
            "Axis 3: Promotional Targeting) as versioned tools for autonomous "
            "invocation by the Operational Agent and BI dashboards.\n\n"
            "Authentication: supply a valid ``X-API-Key`` header for all ``/run`` "
            "and ``/crossvalidate`` endpoints. The ``GET /tools`` catalogue endpoint "
            "is publicly accessible."
        ),
        version=API_VERSION,
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs",
        redoc_url="/v1/redoc",
        license_info={
            "name": "Internal — Not for public distribution",
        },
    )

    # ── CORS (allow all origins in dev; restrict in prod via env) ──────────
    allowed_origins = os.getenv("CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in allowed_origins],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type", "Accept"],
    )

    # ── Request-ID / structured logging middleware ─────────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        start = time.perf_counter()
        logger.info(
            '{"event": "request_start", "request_id": "%s", "method": "%s", "path": "%s"}',
            request_id, request.method, request.url.path,
        )
        try:
            response: Response = await call_next(request)
        except Exception:
            logger.exception(
                '{"event": "request_error", "request_id": "%s"}', request_id
            )
            raise

        duration = round(time.perf_counter() - start, 3)
        logger.info(
            '{"event": "request_end", "request_id": "%s", "status": %d, "duration_s": %s}',
            request_id, response.status_code, duration,
        )
        response.headers["X-Request-ID"] = request_id
        return response

    # ── Health check ───────────────────────────────────────────────────────
    @app.get(
        "/health",
        response_model=HealthResponse,
        summary="Health check",
        description="Returns ``{status: ok}`` when the API is running. No authentication required.",
        tags=["Meta"],
    )
    async def health() -> HealthResponse:
        return HealthResponse(version=API_VERSION)

    # ── Tool routes under /v1 prefix ───────────────────────────────────────
    app.include_router(tools_router, prefix="/v1")

    # ── Audit routes under /v1 prefix ──────────────────────────────────────
    app.include_router(audit_router, prefix="/v1")

    # ── Agent BFF route under /v1 prefix ───────────────────────────────────
    app.include_router(agent_router, prefix="/v1")

    # ── Agent Chat route under /v1 prefix ──────────────────────────────────
    app.include_router(chat_router, prefix="/v1")

    logger.info(
        '{"event": "startup", "api_version": "%s", "log_level": "%s"}',
        API_VERSION, _LOG_LEVEL,
    )

    return app


app = create_app()
