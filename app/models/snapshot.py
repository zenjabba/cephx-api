"""Pydantic models for snapshot schedule operations."""

import re
from typing import List, Literal, Union

from pydantic import BaseModel, Field, field_validator


class SnapshotRetentionPolicy(BaseModel):
    """Retention policy for snapshots."""

    hourly: Union[int, None] = Field(
        None,
        description="Number of hourly snapshots to retain",
        ge=1,
        le=8760,  # Max 1 year of hourly snapshots
    )
    daily: Union[int, None] = Field(
        None,
        description="Number of daily snapshots to retain",
        ge=1,
        le=3650,  # Max 10 years
    )
    weekly: Union[int, None] = Field(
        None,
        description="Number of weekly snapshots to retain",
        ge=1,
        le=520,  # Max 10 years
    )
    monthly: Union[int, None] = Field(
        None,
        description="Number of monthly snapshots to retain",
        ge=1,
        le=120,  # Max 10 years
    )
    yearly: Union[int, None] = Field(
        None,
        description="Number of yearly snapshots to retain",
        ge=1,
        le=100,
    )


class AddSnapshotScheduleRequest(BaseModel):
    """Request model for adding a snapshot schedule."""

    path: str = Field(
        default="/",
        description="CephFS path to schedule snapshots for",
        min_length=1,
        max_length=4096,
    )
    schedule: str = Field(
        ...,
        description="Snapshot schedule in format <number><unit> (e.g., 1h, 6h, 1d, 1w, 1M, 1y)",
        min_length=2,
        max_length=10,
    )
    start_time: Union[str, None] = Field(
        None,
        description="Start time in HH:MM:SS format (optional)",
        pattern="^([0-1][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]$",
    )
    retention: Union[SnapshotRetentionPolicy, None] = Field(
        None,
        description="Retention policy for snapshots (optional)",
    )

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Validate CephFS path format.

        Args:
            v: Path to validate

        Returns:
            Validated path

        Raises:
            ValueError: If path format is invalid
        """
        if not v.startswith("/"):
            raise ValueError("Path must start with /")
        if v != "/" and v.endswith("/"):
            raise ValueError("Path must not end with / (except for root)")
        if "//" in v:
            raise ValueError("Path must not contain double slashes")
        # Check for invalid characters (basic validation)
        invalid_chars = ["\0", "\n", "\r", "\t"]
        if any(char in v for char in invalid_chars):
            raise ValueError("Path contains invalid characters")
        return v

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, v: str) -> str:
        """Validate schedule format.

        Args:
            v: Schedule string to validate

        Returns:
            Validated schedule

        Raises:
            ValueError: If schedule format is invalid
        """
        pattern = r"^(\d+)(h|d|w|M|y)$"
        if not re.match(pattern, v):
            raise ValueError(
                "Invalid schedule format. Must be <number><unit> where unit is h, d, w, M, or y. "
                "Examples: 1h (hourly), 6h (every 6 hours), 1d (daily), 1w (weekly), 1M (monthly), 1y (yearly)"
            )

        # Extract number and validate it's positive
        match = re.match(pattern, v)
        if match:
            number = int(match.group(1))
            unit = match.group(2)

            if number <= 0:
                raise ValueError("Schedule number must be positive")

            # Validate reasonable ranges
            max_values = {"h": 8760, "d": 3650, "w": 520, "M": 1200, "y": 100}
            if number > max_values[unit]:
                raise ValueError(
                    f"Schedule number too large for unit {unit}. Maximum is {max_values[unit]}"
                )

        return v


class SnapshotScheduleRetention(BaseModel):
    """Retention configuration in a snapshot schedule."""

    h: Union[int, None] = Field(None, description="Hourly retention count", alias="h")
    d: Union[int, None] = Field(None, description="Daily retention count", alias="d")
    w: Union[int, None] = Field(None, description="Weekly retention count", alias="w")
    m: Union[int, None] = Field(None, description="Monthly retention count", alias="m")
    y: Union[int, None] = Field(None, description="Yearly retention count", alias="y")

    class Config:
        """Pydantic config."""

        populate_by_name = True


class SnapshotScheduleInfo(BaseModel):
    """Information about a snapshot schedule."""

    path: str = Field(..., description="CephFS path")
    schedule: str = Field(..., description="Schedule string")
    retention: Union[SnapshotScheduleRetention, None] = Field(
        None,
        description="Retention configuration",
    )
    start: Union[str, None] = Field(None, description="Start time")
    subvol: Union[str, None] = Field(None, description="Subvolume (if applicable)")


class SnapshotScheduleStatusResponse(BaseModel):
    """Response model for snapshot schedule status."""

    path: str = Field(..., description="CephFS path")
    schedules: List[SnapshotScheduleInfo] = Field(
        ...,
        description="List of snapshot schedules for this path",
    )
    fs_name: str = Field(..., description="Filesystem name")


class ListSnapshotSchedulesResponse(BaseModel):
    """Response model for listing all snapshot schedules."""

    schedules: List[SnapshotScheduleInfo] = Field(
        ...,
        description="List of snapshot schedules",
    )
    count: int = Field(..., description="Total number of schedules")
    fs_name: str = Field(..., description="Filesystem name")


class SnapshotInfo(BaseModel):
    """Information about a snapshot."""

    name: str = Field(..., description="Snapshot name")
    path: str = Field(..., description="Path where snapshot was taken")
    created: str = Field(..., description="Creation timestamp")
    size_bytes: Union[int, None] = Field(None, description="Snapshot size in bytes")


class ListSnapshotsResponse(BaseModel):
    """Response model for listing snapshots."""

    snapshots: List[SnapshotInfo] = Field(..., description="List of snapshots")
    count: int = Field(..., description="Total number of snapshots")
    path: str = Field(..., description="Path queried")
    fs_name: str = Field(..., description="Filesystem name")


class AddSnapshotScheduleResponse(BaseModel):
    """Response model for adding a snapshot schedule."""

    path: str = Field(..., description="CephFS path")
    schedule: str = Field(..., description="Schedule string")
    start_time: Union[str, None] = Field(None, description="Start time")
    retention: Union[SnapshotRetentionPolicy, None] = Field(
        None,
        description="Retention policy",
    )
    fs_name: str = Field(..., description="Filesystem name")
    message: str = Field(
        default="Snapshot schedule added successfully",
        description="Success message",
    )
