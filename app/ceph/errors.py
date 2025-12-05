"""Custom exceptions for Ceph operations."""

from typing import Any, Dict, Union


class CephCommandError(Exception):
    """Base exception for Ceph command errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "CEPH_COMMAND_ERROR",
        status_code: int = 500,
        details: Union[Dict[str, Any], None] = None,
    ) -> None:
        """Initialize CephCommandError.

        Args:
            message: Human-readable error message
            error_code: Machine-readable error code
            status_code: HTTP status code to return
            details: Additional error details
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}


class CephClusterUnavailable(CephCommandError):
    """Ceph cluster is unavailable or unreachable."""

    def __init__(self, message: str = "Ceph cluster is unavailable", **kwargs: Any) -> None:
        """Initialize CephClusterUnavailable."""
        kwargs.setdefault("error_code", "CEPH_CLUSTER_UNAVAILABLE")
        kwargs.setdefault("status_code", 503)
        super().__init__(message, **kwargs)


class CephAuthNotFound(CephCommandError):
    """Ceph auth entity not found."""

    def __init__(self, entity: str, **kwargs: Any) -> None:
        """Initialize CephAuthNotFound.

        Args:
            entity: The auth entity that was not found
            **kwargs: Additional arguments
        """
        message = f"Auth entity not found: {entity}"
        kwargs.setdefault("error_code", "CEPH_AUTH_NOT_FOUND")
        kwargs.setdefault("status_code", 404)
        kwargs.setdefault("details", {})
        kwargs["details"]["entity"] = entity
        super().__init__(message, **kwargs)


class CephFsNotFound(CephCommandError):
    """CephFS filesystem not found."""

    def __init__(self, fs_name: str, **kwargs: Any) -> None:
        """Initialize CephFsNotFound.

        Args:
            fs_name: The filesystem name that was not found
            **kwargs: Additional arguments
        """
        message = f"CephFS filesystem not found: {fs_name}"
        kwargs.setdefault("error_code", "CEPH_FS_NOT_FOUND")
        kwargs.setdefault("status_code", 404)
        kwargs.setdefault("details", {})
        kwargs["details"]["fs_name"] = fs_name
        super().__init__(message, **kwargs)


class CephPathNotFound(CephCommandError):
    """Path not found in CephFS."""

    def __init__(self, path: str, **kwargs: Any) -> None:
        """Initialize CephPathNotFound.

        Args:
            path: The path that was not found
            **kwargs: Additional arguments
        """
        message = f"Path not found: {path}"
        kwargs.setdefault("error_code", "CEPH_PATH_NOT_FOUND")
        kwargs.setdefault("status_code", 404)
        kwargs.setdefault("details", {})
        kwargs["details"]["path"] = path
        super().__init__(message, **kwargs)


class CephSnapshotNotFound(CephCommandError):
    """Snapshot not found."""

    def __init__(self, snapshot_name: str, path: str, **kwargs: Any) -> None:
        """Initialize CephSnapshotNotFound.

        Args:
            snapshot_name: The snapshot name that was not found
            path: The path where the snapshot was expected
            **kwargs: Additional arguments
        """
        message = f"Snapshot not found: {snapshot_name} at {path}"
        kwargs.setdefault("error_code", "CEPH_SNAPSHOT_NOT_FOUND")
        kwargs.setdefault("status_code", 404)
        kwargs.setdefault("details", {})
        kwargs["details"]["snapshot_name"] = snapshot_name
        kwargs["details"]["path"] = path
        super().__init__(message, **kwargs)


class CephSnapshotExists(CephCommandError):
    """Snapshot already exists."""

    def __init__(self, snapshot_name: str, path: str, **kwargs: Any) -> None:
        """Initialize CephSnapshotExists.

        Args:
            snapshot_name: The snapshot name that already exists
            path: The path where the snapshot exists
            **kwargs: Additional arguments
        """
        message = f"Snapshot already exists: {snapshot_name} at {path}"
        kwargs.setdefault("error_code", "CEPH_SNAPSHOT_EXISTS")
        kwargs.setdefault("status_code", 409)
        kwargs.setdefault("details", {})
        kwargs["details"]["snapshot_name"] = snapshot_name
        kwargs["details"]["path"] = path
        super().__init__(message, **kwargs)


class CephInvalidPath(CephCommandError):
    """Invalid path format."""

    def __init__(self, path: str, reason: str, **kwargs: Any) -> None:
        """Initialize CephInvalidPath.

        Args:
            path: The invalid path
            reason: Reason why the path is invalid
            **kwargs: Additional arguments
        """
        message = f"Invalid path: {path} - {reason}"
        kwargs.setdefault("error_code", "CEPH_INVALID_PATH")
        kwargs.setdefault("status_code", 400)
        kwargs.setdefault("details", {})
        kwargs["details"]["path"] = path
        kwargs["details"]["reason"] = reason
        super().__init__(message, **kwargs)


class CephQuotaError(CephCommandError):
    """Error setting or getting quota."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        """Initialize CephQuotaError."""
        kwargs.setdefault("error_code", "CEPH_QUOTA_ERROR")
        kwargs.setdefault("status_code", 500)
        super().__init__(message, **kwargs)


class CephPermissionDenied(CephCommandError):
    """Permission denied for Ceph operation."""

    def __init__(self, message: str = "Permission denied", **kwargs: Any) -> None:
        """Initialize CephPermissionDenied."""
        kwargs.setdefault("error_code", "CEPH_PERMISSION_DENIED")
        kwargs.setdefault("status_code", 403)
        super().__init__(message, **kwargs)


class CephTimeout(CephCommandError):
    """Ceph command timeout."""

    def __init__(self, message: str = "Ceph command timed out", **kwargs: Any) -> None:
        """Initialize CephTimeout."""
        kwargs.setdefault("error_code", "CEPH_TIMEOUT")
        kwargs.setdefault("status_code", 504)
        super().__init__(message, **kwargs)


class CephAuthAlreadyExists(CephCommandError):
    """Ceph auth entity already exists."""

    def __init__(self, entity: str, **kwargs: Any) -> None:
        """Initialize CephAuthAlreadyExists.

        Args:
            entity: The auth entity that already exists
            **kwargs: Additional arguments
        """
        message = f"Auth entity already exists: {entity}"
        kwargs.setdefault("error_code", "CEPH_AUTH_ALREADY_EXISTS")
        kwargs.setdefault("status_code", 409)
        kwargs.setdefault("details", {})
        kwargs["details"]["entity"] = entity
        super().__init__(message, **kwargs)


class CephScheduleNotFound(CephCommandError):
    """Snapshot schedule not found."""

    def __init__(self, path: str, schedule: Union[str, None] = None, **kwargs: Any) -> None:
        """Initialize CephScheduleNotFound.

        Args:
            path: The path where schedule was expected
            schedule: The schedule that was not found (optional)
            **kwargs: Additional arguments
        """
        if schedule:
            message = f"Snapshot schedule not found: {schedule} at {path}"
        else:
            message = f"No snapshot schedules found at {path}"
        kwargs.setdefault("error_code", "SCHEDULE_NOT_FOUND")
        kwargs.setdefault("status_code", 404)
        kwargs.setdefault("details", {})
        kwargs["details"]["path"] = path
        if schedule:
            kwargs["details"]["schedule"] = schedule
        super().__init__(message, **kwargs)


class CephInvalidSchedule(CephCommandError):
    """Invalid schedule format."""

    def __init__(self, schedule: str, reason: str, **kwargs: Any) -> None:
        """Initialize CephInvalidSchedule.

        Args:
            schedule: The invalid schedule
            reason: Reason why the schedule is invalid
            **kwargs: Additional arguments
        """
        message = f"Invalid schedule format: {schedule} - {reason}"
        kwargs.setdefault("error_code", "INVALID_SCHEDULE")
        kwargs.setdefault("status_code", 400)
        kwargs.setdefault("details", {})
        kwargs["details"]["schedule"] = schedule
        kwargs["details"]["reason"] = reason
        kwargs["details"]["examples"] = [
            "1h (hourly)",
            "6h (every 6 hours)",
            "1d (daily)",
            "1w (weekly)",
            "1M (monthly)",
            "1y (yearly)",
        ]
        super().__init__(message, **kwargs)
