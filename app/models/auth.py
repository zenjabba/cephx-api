"""Pydantic models for CephX authentication."""

import re
from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field, field_validator


class CephXCapabilities(BaseModel):
    """CephX capabilities for different subsystems."""

    mds: Union[str, None] = Field(None, description="MDS capabilities (e.g., 'allow rw')")
    mon: Union[str, None] = Field(None, description="Monitor capabilities (e.g., 'allow r')")
    osd: Union[str, None] = Field(None, description="OSD capabilities (e.g., 'allow rw pool=mypool')")
    mgr: Union[str, None] = Field(None, description="Manager capabilities (e.g., 'allow r')")

    @field_validator("mds", "mon", "osd", "mgr")
    @classmethod
    def validate_capability(cls, v: Union[str, None]) -> Union[str, None]:
        """Validate capability string format."""
        if v is None:
            return v
        if not v.strip():
            return None
        return v.strip()

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary, excluding None values."""
        return {k: v for k, v in self.model_dump().items() if v is not None}

    def is_empty(self) -> bool:
        """Check if all capabilities are None or empty."""
        return all(v is None or not v.strip() for v in self.model_dump().values())


class CreateAuthRequest(BaseModel):
    """Request model for creating CephX authentication."""

    client_name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Client name (without 'client.' prefix)",
        examples=["testuser"],
    )
    capabilities: CephXCapabilities = Field(
        ...,
        description="Capabilities for different Ceph subsystems",
    )

    @field_validator("client_name")
    @classmethod
    def validate_client_name(cls, v: str) -> str:
        """Validate client name format.

        Args:
            v: Client name to validate

        Returns:
            Validated client name

        Raises:
            ValueError: If client name is invalid
        """
        # Remove client. prefix if provided
        if v.startswith("client."):
            v = v[7:]

        # Check length
        if not 1 <= len(v) <= 64:
            raise ValueError("Client name must be between 1 and 64 characters")

        # Check characters (alphanumeric, underscore, hyphen only)
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "Client name can only contain alphanumeric characters, underscores, and hyphens"
            )

        return v

    def validate_capabilities(self) -> None:
        """Validate that at least one capability is specified.

        Raises:
            ValueError: If no capabilities are specified
        """
        if self.capabilities.is_empty():
            raise ValueError("At least one capability must be specified")


class UpdateCapsRequest(BaseModel):
    """Request model for updating CephX capabilities."""

    capabilities: CephXCapabilities = Field(
        ...,
        description="New capabilities (empty dict means suspend/remove all caps)",
    )


class CephXAuthEntity(BaseModel):
    """CephX authentication entity details."""

    entity: str = Field(..., description="Entity name (e.g., 'client.testuser')")
    key: str = Field(..., description="Secret key for authentication")
    caps: Dict[str, str] = Field(
        default_factory=dict,
        description="Capabilities for different subsystems",
    )

    @property
    def client_name(self) -> str:
        """Extract client name without 'client.' prefix."""
        if self.entity.startswith("client."):
            return self.entity[7:]
        return self.entity


class CephXAuthList(BaseModel):
    """List of CephX authentication entities."""

    clients: List[CephXAuthEntity] = Field(
        default_factory=list,
        description="List of authentication entities",
    )
    total: int = Field(..., description="Total number of entities")
    offset: int = Field(0, description="Pagination offset")
    limit: int = Field(100, description="Pagination limit")


class APIResponse(BaseModel):
    """Standard API response wrapper."""

    status: str = Field(..., description="Response status (success or error)")
    data: Union[Dict[str, Any], List[Any], None] = Field(
        None,
        description="Response data",
    )
    code: Union[str, None] = Field(None, description="Error code (only for errors)")
    message: Union[str, None] = Field(None, description="Error message (only for errors)")
    details: Union[Dict[str, Any], None] = Field(None, description="Additional error details")

    @classmethod
    def success(cls, data: Union[Dict[str, Any], List[Any]]) -> "APIResponse":
        """Create a success response.

        Args:
            data: Response data

        Returns:
            APIResponse instance
        """
        return cls(status="success", data=data)

    @classmethod
    def error(
        cls,
        code: str,
        message: str,
        details: Union[Dict[str, Any], None] = None,
    ) -> "APIResponse":
        """Create an error response.

        Args:
            code: Error code
            message: Error message
            details: Additional error details

        Returns:
            APIResponse instance
        """
        return cls(
            status="error",
            code=code,
            message=message,
            details=details,
        )
