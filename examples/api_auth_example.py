#!/usr/bin/env python3
"""
Example: API Key Authentication Middleware

This example demonstrates how to integrate the CLI-managed API keys
with a FastAPI application for authentication.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Optional

import bcrypt
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

# Configuration
DB_PATH = "/var/lib/cephx-api/api.db"


class APIKeyAuth:
    """API Key Authentication handler."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def verify_api_key(self, api_key: str) -> Optional[dict]:
        """
        Verify an API key against the database.

        Args:
            api_key: The API key to verify

        Returns:
            API key record if valid, None otherwise
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Get all enabled keys (we need to check hashes)
            cursor.execute(
                "SELECT * FROM api_keys WHERE enabled = 1"
            )
            keys = cursor.fetchall()

            for key in keys:
                # Verify hash
                try:
                    if bcrypt.checkpw(api_key.encode('utf-8'), key['key_hash'].encode('utf-8')):
                        # Check expiration
                        if key['expires_at']:
                            expires = datetime.fromisoformat(key['expires_at'].replace('Z', '+00:00'))
                            if datetime.now(timezone.utc) > expires:
                                return None  # Key expired

                        # Update last used timestamp
                        now = datetime.now(timezone.utc).isoformat()
                        cursor.execute(
                            "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
                            (now, key['id'])
                        )
                        conn.commit()

                        return dict(key)
                except Exception:
                    continue

            return None

    def log_request(
        self,
        api_key_prefix: str,
        source_ip: str,
        method: str,
        endpoint: str,
        status_code: int,
        response_time_ms: float,
        user_agent: Optional[str] = None,
        error_message: Optional[str] = None,
    ):
        """Log API request to audit log."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO audit_log
                (timestamp, api_key_prefix, source_ip, method, endpoint,
                 status_code, response_time_ms, user_agent, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                api_key_prefix,
                source_ip,
                method,
                endpoint,
                status_code,
                response_time_ms,
                user_agent,
                error_message,
            ))
            conn.commit()


# Initialize FastAPI app
app = FastAPI(title="Ceph Management API")
auth_handler = APIKeyAuth(DB_PATH)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Authentication middleware."""
    import time

    start_time = time.time()

    # Skip auth for docs and health endpoints
    if request.url.path in ["/docs", "/redoc", "/openapi.json", "/health"]:
        return await call_next(request)

    # Get API key from header
    api_key = request.headers.get("X-API-Key")

    if not api_key:
        response_time = (time.time() - start_time) * 1000
        auth_handler.log_request(
            api_key_prefix="unknown",
            source_ip=request.client.host,
            method=request.method,
            endpoint=request.url.path,
            status_code=401,
            response_time_ms=response_time,
            user_agent=request.headers.get("user-agent"),
            error_message="Missing API key",
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Missing API key"},
        )

    # Verify API key
    key_data = auth_handler.verify_api_key(api_key)

    if not key_data:
        response_time = (time.time() - start_time) * 1000
        # Extract prefix for logging (first 15 chars)
        api_key_prefix = api_key[:15] if len(api_key) >= 15 else api_key
        auth_handler.log_request(
            api_key_prefix=api_key_prefix,
            source_ip=request.client.host,
            method=request.method,
            endpoint=request.url.path,
            status_code=401,
            response_time_ms=response_time,
            user_agent=request.headers.get("user-agent"),
            error_message="Invalid or expired API key",
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Invalid or expired API key"},
        )

    # Store key data in request state for use in endpoints
    request.state.api_key = key_data

    # Process request
    response = await call_next(request)

    # Log successful request
    response_time = (time.time() - start_time) * 1000
    api_key_prefix = api_key[:15] if len(api_key) >= 15 else api_key
    auth_handler.log_request(
        api_key_prefix=api_key_prefix,
        source_ip=request.client.host,
        method=request.method,
        endpoint=request.url.path,
        status_code=response.status_code,
        response_time_ms=response_time,
        user_agent=request.headers.get("user-agent"),
    )

    return response


def require_permission(permission: str):
    """
    Decorator to require specific permission for an endpoint.

    Usage:
        @app.get("/api/v1/snapshots")
        @require_permission("snapshot:read")
        async def list_snapshots(request: Request):
            ...
    """
    def decorator(func):
        async def wrapper(request: Request, *args, **kwargs):
            key_data = request.state.api_key
            permissions = key_data['permissions'].split(',')

            # Check for admin permission or specific permission
            if 'admin:*' in permissions or permission in permissions:
                return await func(request, *args, **kwargs)

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}",
            )

        return wrapper
    return decorator


# Example endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint (no auth required)."""
    return {"status": "healthy"}


@app.get("/api/v1/auth/info")
async def auth_info(request: Request):
    """Get information about the current API key."""
    key_data = request.state.api_key
    return {
        "name": key_data['name'],
        "permissions": key_data['permissions'].split(','),
        "rate_limit": key_data['rate_limit'],
        "expires_at": key_data['expires_at'],
    }


@app.get("/api/v1/snapshots")
async def list_snapshots(request: Request):
    """List snapshots (requires snapshot:read permission)."""
    key_data = request.state.api_key
    permissions = key_data['permissions'].split(',')

    if 'admin:*' not in permissions and 'snapshot:read' not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission: snapshot:read",
        )

    return {
        "snapshots": [
            {"id": 1, "name": "snapshot-1", "size": 1024},
            {"id": 2, "name": "snapshot-2", "size": 2048},
        ]
    }


@app.post("/api/v1/snapshots")
async def create_snapshot(request: Request, name: str):
    """Create snapshot (requires snapshot:write permission)."""
    key_data = request.state.api_key
    permissions = key_data['permissions'].split(',')

    if 'admin:*' not in permissions and 'snapshot:write' not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required permission: snapshot:write",
        )

    return {
        "id": 3,
        "name": name,
        "status": "created",
    }


if __name__ == "__main__":
    import uvicorn

    print("Starting Ceph Management API...")
    print(f"Database: {DB_PATH}")
    print("\nCreate API keys with:")
    print("  python -m app.cli create-api-key --name 'Test' --permissions 'snapshot:read'")
    print("\nTest authentication with:")
    print("  curl -H 'X-API-Key: your_key_here' http://localhost:8080/api/v1/auth/info")

    uvicorn.run(app, host="0.0.0.0", port=8080)
