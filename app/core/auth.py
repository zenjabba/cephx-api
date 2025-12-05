"""Authentication and authorization middleware."""

from typing import Annotated, List, Union

from fastapi import Depends, Header, Request

from .config import get_settings
from .exceptions import InvalidAPIKeyError, PermissionDeniedError


class AuthContext:
    """Authentication context for a request."""

    def __init__(self, user: str, permissions: List[str]) -> None:
        """Initialize auth context.

        Args:
            user: Username from API key
            permissions: List of permissions granted to user
        """
        self.user = user
        self.permissions = permissions

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission.

        Args:
            permission: Permission to check (e.g., 'fs:write')

        Returns:
            True if user has permission, False otherwise
        """
        # Check for exact match or wildcard
        return permission in self.permissions or "*" in self.permissions

    def require_permission(self, permission: str) -> None:
        """Require a specific permission, raising exception if not granted.

        Args:
            permission: Required permission

        Raises:
            PermissionDeniedError: If user lacks required permission
        """
        if not self.has_permission(permission):
            raise PermissionDeniedError(permission)


async def verify_api_key(
    request: Request,
    x_api_key: Annotated[Union[str, None], Header()] = None,
) -> AuthContext:
    """Verify API key from request header.

    Args:
        request: FastAPI request object
        x_api_key: API key from X-API-Key header

    Returns:
        AuthContext with user info and permissions

    Raises:
        InvalidAPIKeyError: If API key is invalid or missing
    """
    settings = get_settings()

    # Check for API key in header
    api_key = x_api_key

    if not api_key:
        raise InvalidAPIKeyError({"reason": "API key not provided in X-API-Key header"})

    # Validate API key
    key_info = settings.api_keys.get(api_key)

    if not key_info:
        raise InvalidAPIKeyError({"reason": "Invalid API key"})

    # Return auth context
    return AuthContext(
        user=key_info["name"],
        permissions=key_info["permissions"],
    )


async def require_fs_read(
    auth: Annotated[AuthContext, Depends(verify_api_key)],
) -> AuthContext:
    """Dependency that requires fs:read permission.

    Args:
        auth: Authentication context

    Returns:
        Authentication context

    Raises:
        PermissionDeniedError: If user lacks fs:read permission
    """
    auth.require_permission("fs:read")
    return auth


async def require_fs_write(
    auth: Annotated[AuthContext, Depends(verify_api_key)],
) -> AuthContext:
    """Dependency that requires fs:write permission.

    Args:
        auth: Authentication context

    Returns:
        Authentication context

    Raises:
        PermissionDeniedError: If user lacks fs:write permission
    """
    auth.require_permission("fs:write")
    return auth
