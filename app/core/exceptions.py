"""Custom exception classes for the API."""

from typing import Dict, Union
from typing import Any


class CephAPIException(Exception):
    """Base exception for all Ceph API errors."""

    def __init__(
        self,
        message: str,
        code: str,
        status_code: int = 500,
        details: Union[Union[Dict[str, Any], None]] = None,
    ) -> None:
        """Initialize exception with error details.

        Args:
            message: Human-readable error message
            code: Error code identifier
            status_code: HTTP status code
            details: Additional error details
        """
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class FilesystemAlreadyExistsError(CephAPIException):
    """Raised when attempting to create a filesystem that already exists."""

    def __init__(self, name: str, details: Union[Union[Dict[str, Any], None]] = None) -> None:
        """Initialize with filesystem name."""
        super().__init__(
            message=f"Filesystem '{name}' already exists",
            code="FS_ALREADY_EXISTS",
            status_code=409,
            details=details,
        )


class FilesystemNotFoundError(CephAPIException):
    """Raised when a filesystem cannot be found."""

    def __init__(self, name: str, details: Union[Union[Dict[str, Any], None]] = None) -> None:
        """Initialize with filesystem name."""
        super().__init__(
            message=f"Filesystem '{name}' not found",
            code="FS_NOT_FOUND",
            status_code=404,
            details=details,
        )


class InvalidCrushRuleError(CephAPIException):
    """Raised when a CRUSH rule does not exist or is invalid."""

    def __init__(self, rule: str, details: Union[Union[Dict[str, Any], None]] = None) -> None:
        """Initialize with rule name."""
        super().__init__(
            message=f"CRUSH rule '{rule}' does not exist or is invalid",
            code="INVALID_CRUSH_RULE",
            status_code=400,
            details=details,
        )


class ConfirmationRequiredError(CephAPIException):
    """Raised when a destructive operation requires confirmation."""

    def __init__(self, message: str, details: Union[Union[Dict[str, Any], None]] = None) -> None:
        """Initialize with custom message."""
        super().__init__(
            message=message,
            code="CONFIRMATION_REQUIRED",
            status_code=400,
            details=details,
        )


class CephCommandFailedError(CephAPIException):
    """Raised when a Ceph command execution fails."""

    def __init__(
        self,
        command: str,
        exit_code: int,
        stderr: str,
        details: Union[Union[Dict[str, Any], None]] = None,
    ) -> None:
        """Initialize with command execution details."""
        error_details = details or {}
        error_details.update({
            "command": command,
            "exit_code": exit_code,
            "stderr": stderr,
        })
        super().__init__(
            message=f"Ceph command failed: {command}",
            code="CEPH_COMMAND_FAILED",
            status_code=500,
            details=error_details,
        )


class PermissionDeniedError(CephAPIException):
    """Raised when user lacks required permissions."""

    def __init__(
        self,
        required_permission: str,
        details: Union[Union[Dict[str, Any], None]] = None,
    ) -> None:
        """Initialize with required permission."""
        super().__init__(
            message=f"Permission denied. Required permission: {required_permission}",
            code="PERMISSION_DENIED",
            status_code=403,
            details=details or {"required_permission": required_permission},
        )


class InvalidAPIKeyError(CephAPIException):
    """Raised when API key is invalid or missing."""

    def __init__(self, details: Union[Union[Dict[str, Any], None]] = None) -> None:
        """Initialize with default message."""
        super().__init__(
            message="Invalid or missing API key",
            code="INVALID_API_KEY",
            status_code=401,
            details=details,
        )


class SnapshotScheduleNotFoundError(CephAPIException):
    """Raised when a snapshot schedule is not found."""

    def __init__(
        self,
        path: str,
        schedule: Union[str, None] = None,
        details: Union[Union[Dict[str, Any], None]] = None,
    ) -> None:
        """Initialize with path and optional schedule."""
        error_details = details or {}
        error_details["path"] = path
        if schedule:
            error_details["schedule"] = schedule
            message = f"Snapshot schedule '{schedule}' not found at path '{path}'"
        else:
            message = f"No snapshot schedules found at path '{path}'"

        super().__init__(
            message=message,
            code="SCHEDULE_NOT_FOUND",
            status_code=404,
            details=error_details,
        )


class InvalidScheduleFormatError(CephAPIException):
    """Raised when snapshot schedule format is invalid."""

    def __init__(
        self,
        schedule: str,
        reason: str,
        details: Union[Union[Dict[str, Any], None]] = None,
    ) -> None:
        """Initialize with schedule and reason."""
        error_details = details or {}
        error_details.update({
            "schedule": schedule,
            "reason": reason,
            "examples": [
                "1h (hourly)",
                "6h (every 6 hours)",
                "1d (daily)",
                "1w (weekly)",
                "1M (monthly)",
                "1y (yearly)",
            ],
        })

        super().__init__(
            message=f"Invalid schedule format '{schedule}': {reason}",
            code="INVALID_SCHEDULE",
            status_code=400,
            details=error_details,
        )
