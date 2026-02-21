"""OSD management endpoints."""

import logging
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends

from app.core.auth import AuthContext, verify_api_key
from app.core.exceptions import OSDNotFoundError
from app.core.logging import audit_logger
from app.models.osd import OSDFlagRequest, OSDFlagResponse, OSDStatusResponse
from app.services.ceph_client import ceph_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["OSD"])


async def require_osd_read(
    auth: Annotated[AuthContext, Depends(verify_api_key)],
) -> AuthContext:
    auth.require_permission("osd:read")
    return auth


async def require_osd_write(
    auth: Annotated[AuthContext, Depends(verify_api_key)],
) -> AuthContext:
    auth.require_permission("osd:write")
    return auth


@router.get("/{osd_id}/status", response_model=Dict[str, Any])
async def get_osd_status(
    osd_id: int,
    auth: Annotated[AuthContext, Depends(require_osd_read)],
) -> Dict[str, Any]:
    """Get the UP/IN status of a specific OSD."""
    osd_dump = ceph_client.execute_command(
        ["osd", "dump", "--format", "json"],
        parse_json=True,
    )

    for osd_entry in osd_dump.get("osds", []):
        if osd_entry.get("osd") == osd_id:
            response_data = OSDStatusResponse(
                osd=osd_id,
                up=osd_entry.get("up", 0),
                **{"in": osd_entry.get("in", 0)},
            )

            audit_logger.log_operation(
                operation="READ",
                resource=f"osd:{osd_id}",
                user=auth.user,
                status="SUCCESS",
                details={"up": response_data.up, "in": response_data.in_},
            )

            return {
                "status": "success",
                "data": response_data.model_dump(by_alias=True),
            }

    raise OSDNotFoundError(osd_id)


@router.post("/flags", response_model=Dict[str, Any])
async def set_osd_flag(
    request: OSDFlagRequest,
    auth: Annotated[AuthContext, Depends(require_osd_write)],
) -> Dict[str, Any]:
    """Set or unset a cluster-wide OSD flag."""
    ceph_client.execute_command(
        ["osd", request.action, request.flag],
    )

    message = f"{request.flag} is {request.action}"
    response_data = OSDFlagResponse(ok=True, message=message)

    audit_logger.log_operation(
        operation="WRITE",
        resource=f"osd:flag:{request.flag}",
        user=auth.user,
        status="SUCCESS",
        details={"flag": request.flag, "action": request.action},
    )

    return {
        "status": "success",
        "data": response_data.model_dump(),
    }
