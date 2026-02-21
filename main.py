"""Thin wrapper re-exporting the canonical app from app.main.

All route registration, exception handlers, and startup/shutdown events
live in app/main.py. This file exists so that:
  - `python main.py` works for local development
  - Test imports like `from main import app` resolve to the full app
"""

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    from app.core.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
