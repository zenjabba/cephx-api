"""Pydantic models for filesystem operations."""

from typing import Any, Dict, List, Literal, Union

from pydantic import BaseModel, Field, field_validator


class CreateFilesystemRequest(BaseModel):
    """Request model for creating a CephFS filesystem."""

    name: str = Field(
        ...,
        description="Filesystem name",
        min_length=1,
        max_length=64,
        pattern="^[a-zA-Z0-9_-]+$",
    )
    crush_rule: str = Field(
        default="replicated_mach2",
        description="CRUSH rule for pools",
    )
    meta_pool_pg: int = Field(
        default=16,
        description="Number of placement groups for metadata pool",
        ge=1,
        le=32768,
    )
    data_pool_type: Literal["replicated"] = Field(
        default="replicated",
        description="Data pool type (only replicated supported)",
    )
    enable_snapshots: bool = Field(
        default=True,
        description="Enable snapshots on filesystem",
    )
    create_auth: bool = Field(
        default=True,
        description="Create client auth key for filesystem access",
    )
    auth_client_name: Union[str, None] = Field(
        default=None,
        description="Client name for auth (defaults to filesystem name)",
        min_length=1,
        max_length=64,
        pattern="^[a-zA-Z0-9_-]+$",
    )

    @field_validator("auth_client_name")
    @classmethod
    def set_default_auth_name(cls, v: Union[str, None], info) -> Union[str, None]:
        """Set auth_client_name to name if not provided."""
        if v is None and info.data.get("name"):
            return info.data["name"]
        return v


class FilesystemPoolInfo(BaseModel):
    """Pool information for a filesystem."""

    name: str = Field(..., description="Pool name")
    type: str = Field(..., description="Pool type")
    id: int = Field(..., description="Pool ID")


class FilesystemInfo(BaseModel):
    """Information about a CephFS filesystem."""

    name: str = Field(..., description="Filesystem name")
    metadata_pool: str = Field(..., description="Metadata pool name")
    data_pools: List[str] = Field(..., description="Data pool names")
    mds_count: int = Field(..., description="Number of active MDS daemons")


class FilesystemUsageStats(BaseModel):
    """Usage statistics for a filesystem."""

    stored_bytes: int = Field(..., description="Bytes stored (before replication)")
    stored_tb: float = Field(..., description="Terabytes stored (before replication)")
    used_bytes: int = Field(..., description="Bytes used (after replication)")
    objects: int = Field(..., description="Number of objects")
    percent_used: float = Field(..., description="Percentage of pool used")


class FilesystemUsageResponse(BaseModel):
    """Response model for filesystem usage."""

    name: str = Field(..., description="Filesystem name")
    usage: FilesystemUsageStats = Field(..., description="Usage statistics")


class CreateFilesystemResponse(BaseModel):
    """Response model for filesystem creation."""

    name: str = Field(..., description="Filesystem name")
    metadata_pool: str = Field(..., description="Metadata pool name")
    data_pool: str = Field(..., description="Data pool name")
    snapshots_enabled: bool = Field(..., description="Whether snapshots are enabled")
    auth_created: bool = Field(..., description="Whether auth key was created")
    auth_client_name: Union[str, None] = Field(
        None,
        description="Client name for auth",
    )
    auth_key: Union[str, None] = Field(None, description="Authentication key")


class FilesystemWithUsage(FilesystemInfo):
    """Filesystem information with optional usage stats."""

    usage: Union[FilesystemUsageStats, None] = Field(
        None,
        description="Usage statistics (if requested)",
    )


class ListFilesystemsResponse(BaseModel):
    """Response model for listing filesystems."""

    filesystems: List[FilesystemWithUsage] = Field(
        ...,
        description="List of filesystems",
    )
    count: int = Field(..., description="Total number of filesystems")


class APIResponse(BaseModel):
    """Standard API response wrapper."""

    status: Literal["success", "error"] = Field(..., description="Response status")
    data: Union[Any, None] = Field(None, description="Response data")
    code: Union[str, None] = Field(None, description="Error code")
    message: Union[str, None] = Field(None, description="Error message")
    details: Union[Dict[str, Any], None] = Field(None, description="Additional details")
