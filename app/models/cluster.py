"""Pydantic models for cluster endpoints."""

from typing import Any, Dict, List, Union

from pydantic import BaseModel, Field


class MonitorInfo(BaseModel):
    """Monitor information."""

    name: str = Field(..., description="Monitor name")
    addr: str = Field(..., description="Monitor address (IP:port)")
    rank: int = Field(..., description="Monitor rank")


class MonitorsResponse(BaseModel):
    """Response model for monitors endpoint."""

    monitors: List[MonitorInfo] = Field(..., description="List of monitors")
    total: int = Field(..., description="Total number of monitors")


class MonStatus(BaseModel):
    """Monitor status information."""

    epoch: int = Field(..., description="Monmap epoch")
    num_mons: int = Field(..., description="Number of monitors")
    quorum: List[int] = Field(..., description="List of monitor ranks in quorum")


class OSDStatus(BaseModel):
    """OSD status information."""

    num_osds: int = Field(..., description="Total number of OSDs")
    num_up_osds: int = Field(..., description="Number of OSDs that are up")
    num_in_osds: int = Field(..., description="Number of OSDs that are in")


class PGStatus(BaseModel):
    """Placement group status information."""

    num_pgs: int = Field(..., description="Total number of placement groups")
    num_active_clean: int = Field(
        ..., description="Number of PGs in active+clean state"
    )


class ClusterStatusData(BaseModel):
    """Cluster status data."""

    health: str = Field(..., description="Cluster health status")
    mon_status: MonStatus = Field(..., description="Monitor status")
    osd_status: OSDStatus = Field(..., description="OSD status")
    pg_status: PGStatus = Field(..., description="Placement group status")


class ClusterStats(BaseModel):
    """Cluster storage statistics."""

    total_bytes: int = Field(..., description="Total cluster capacity in bytes")
    total_used_bytes: int = Field(..., description="Total used space in bytes")
    total_avail_bytes: int = Field(..., description="Total available space in bytes")


class PoolStats(BaseModel):
    """Pool statistics."""

    stored: int = Field(..., description="Bytes stored (after compression if enabled)")
    objects: int = Field(..., description="Number of objects")
    kb_used: int = Field(..., description="Kilobytes used")
    bytes_used: int = Field(..., description="Bytes used")
    percent_used: float = Field(..., description="Percentage of cluster used")


class PoolInfo(BaseModel):
    """Pool information."""

    name: str = Field(..., description="Pool name")
    id: int = Field(..., description="Pool ID")
    stats: PoolStats = Field(..., description="Pool statistics")


class ClusterDfData(BaseModel):
    """Cluster df data."""

    stats: ClusterStats = Field(..., description="Global cluster statistics")
    pools: List[PoolInfo] = Field(..., description="Per-pool statistics")


class APIResponse(BaseModel):
    """Standard API response wrapper."""

    status: str = Field(..., description="Response status (success or error)")
    data: Any = Field(None, description="Response data")
    code: Union[str, None] = Field(None, description="Error code")
    message: Union[str, None] = Field(None, description="Error message")
    details: Union[Dict[str, Any], None] = Field(None, description="Additional details")
