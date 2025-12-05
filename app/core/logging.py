"""Logging configuration and audit logging."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Union

from .config import get_settings


def setup_logging() -> None:
    """Configure application logging."""
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class AuditLogger:
    """Audit logger for tracking API operations."""

    def __init__(self) -> None:
        """Initialize audit logger."""
        self.settings = get_settings()
        self.logger = logging.getLogger("audit")

        if self.settings.audit_log_enabled:
            # Ensure log directory exists
            log_path = Path(self.settings.audit_log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # Add file handler
            handler = logging.FileHandler(self.settings.audit_log_file)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def log_operation(
        self,
        operation: str,
        resource: str,
        user: str,
        status: str,
        details: Union[Union[Dict[str, Any], None]] = None,
    ) -> None:
        """Log an API operation to the audit log.

        Args:
            operation: Operation type (CREATE, READ, UPDATE, DELETE)
            resource: Resource being operated on (e.g., filesystem:testfs)
            user: User performing the operation
            status: Operation status (SUCCESS, FAILED)
            details: Additional operation details
        """
        if not self.settings.audit_log_enabled:
            return

        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "resource": resource,
            "user": user,
            "status": status,
            "details": details or {},
        }

        self.logger.info(json.dumps(audit_entry))


# Global audit logger instance
audit_logger = AuditLogger()
