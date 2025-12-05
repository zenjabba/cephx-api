"""Database operations and audit logging."""

from typing import Any, Dict, Union

from app.core.logging import audit_logger


def log_audit(
    operation: str,
    resource: str,
    user: str,
    status: str = "SUCCESS",
    details: Union[Union[Dict[str, Any], None]] = None,
) -> None:
    """Log an operation to the audit log.

    Args:
        operation: Operation type (CREATE, READ, UPDATE, DELETE, LIST)
        resource: Resource identifier (e.g., 'auth:client.testuser')
        user: Username performing the operation
        status: Operation status (SUCCESS, FAILED)
        details: Additional details about the operation
    """
    audit_logger.log_operation(
        operation=operation,
        resource=resource,
        user=user,
        status=status,
        details=details,
    )
