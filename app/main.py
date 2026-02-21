"""Main FastAPI application."""

import logging
from typing import Dict

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import CephAPIException
from app.core.logging import setup_logging
from app.models.filesystem import APIResponse
from app.routers import auth, cluster, filesystem, osd, snapshot

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title="Ceph Management API",
    description="REST API for managing Ceph clusters, filesystems, and storage",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# Exception handlers
@app.exception_handler(CephAPIException)
async def ceph_api_exception_handler(
    request: Request,
    exc: CephAPIException,
) -> JSONResponse:
    """Handle CephAPIException and return structured error response."""
    logger.error(
        f"CephAPIException: {exc.code} - {exc.message}",
        extra={"details": exc.details},
    )

    response = APIResponse(
        status="error",
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=response.model_dump(exclude_none=True),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle request validation errors."""
    logger.warning(f"Validation error: {exc.errors()}")

    # Sanitize errors — pydantic ctx.error contains raw Exception objects
    # that aren't JSON serializable
    sanitized = []
    for err in exc.errors():
        clean = {k: v for k, v in err.items() if k != "ctx"}
        if "ctx" in err:
            clean["ctx"] = {k: str(v) for k, v in err["ctx"].items()}
        sanitized.append(clean)

    response = APIResponse(
        status="error",
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details={"errors": sanitized},
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=response.model_dump(exclude_none=True),
    )


@app.exception_handler(Exception)
async def general_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)

    response = APIResponse(
        status="error",
        code="INTERNAL_SERVER_ERROR",
        message="An unexpected error occurred",
        details={"error": str(exc)} if settings.debug else {},
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=response.model_dump(exclude_none=True),
    )


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


# Include routers
app.include_router(
    auth.router,
    prefix=f"{settings.api_v1_prefix}/auth",
    tags=["Authentication"],
)

app.include_router(
    cluster.router,
    prefix=f"{settings.api_v1_prefix}/cluster",
    tags=["Cluster"],
)

app.include_router(
    filesystem.router,
    prefix=f"{settings.api_v1_prefix}/fs",
    tags=["Filesystems"],
)

app.include_router(
    osd.router,
    prefix=f"{settings.api_v1_prefix}/ceph/osd",
    tags=["OSD"],
)

app.include_router(
    snapshot.router,
    prefix=f"{settings.api_v1_prefix}/snapshots",
    tags=["Snapshots"],
)


# Startup event
@app.on_event("startup")
async def startup_event() -> None:
    """Application startup tasks."""
    logger.info("Starting Ceph Management API")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Application shutdown tasks."""
    logger.info("Shutting down Ceph Management API")
