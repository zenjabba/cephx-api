"""Pydantic models for OSD endpoints."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


ALLOWED_OSD_FLAGS = ("noout", "norebalance")


class OSDStatusResponse(BaseModel):
    """Response for individual OSD status."""

    osd: int = Field(..., description="OSD ID")
    up: int = Field(..., description="1 if OSD is up, 0 if down")
    in_: int = Field(..., alias="in", description="1 if OSD is in, 0 if out")

    model_config = {"populate_by_name": True}


class OSDFlagRequest(BaseModel):
    """Request to set/unset a cluster-wide OSD flag."""

    flag: str = Field(..., description="OSD flag to set/unset (noout, norebalance)")
    action: Literal["set", "unset"] = Field(..., description="Whether to set or unset the flag")

    @field_validator("flag")
    @classmethod
    def validate_flag(cls, v: str) -> str:
        if v not in ALLOWED_OSD_FLAGS:
            raise ValueError(f"Flag must be one of: {', '.join(ALLOWED_OSD_FLAGS)}")
        return v


class OSDFlagResponse(BaseModel):
    """Response for OSD flag operations."""

    ok: bool = Field(..., description="Whether the operation succeeded")
    message: str = Field(..., description="Description of the result")
