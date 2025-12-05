"""FastAPI application for Ceph Management API."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.exceptions import CephAPIException
from app.core.logging import setup_logging
from app.routers import cluster

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title="Ceph Management API",
    description="REST API for managing Ceph clusters",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


# Exception handler for CephAPIException
@app.exception_handler(CephAPIException)
async def ceph_exception_handler(
    request: Request,
    exc: CephAPIException,
) -> JSONResponse:
    """Handle Ceph API exceptions.

    Args:
        request: FastAPI request
        exc: CephAPIException instance

    Returns:
        JSON response with error details
    """
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )


# Health check endpoint
@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        Health status
    """
    return {"status": "ok"}


# Include routers
app.include_router(cluster.router, prefix=f"{settings.api_v1_prefix}/cluster")


# Startup event
@app.on_event("startup")
async def startup_event() -> None:
    """Execute on application startup."""
    logger.info("Ceph Management API starting up...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"API prefix: {settings.api_v1_prefix}")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Execute on application shutdown."""
    logger.info("Ceph Management API shutting down...")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8080,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
