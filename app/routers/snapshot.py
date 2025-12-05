"""Snapshot schedule management endpoints for CephFS."""

import logging
from typing import Any, List, Union

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    CephAPIException,
    CephCommandFailedError,
    FilesystemNotFoundError,
    InvalidScheduleFormatError,
    SnapshotScheduleNotFoundError,
)
from app.models.filesystem import APIResponse
from app.models.snapshot import (
    AddSnapshotScheduleRequest,
    AddSnapshotScheduleResponse,
    ListSnapshotSchedulesResponse,
    SnapshotScheduleInfo,
)
from app.services.ceph_client import ceph_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Snapshots"])


def _map_retention_unit(unit: str) -> str:
    """Map retention unit from API format to Ceph format.

    Args:
        unit: API unit name (hourly, daily, weekly, monthly, yearly)

    Returns:
        Ceph unit code (h, d, w, m, y)
    """
    mapping = {
        "hourly": "h",
        "daily": "d",
        "weekly": "w",
        "monthly": "m",
        "yearly": "y",
    }
    return mapping.get(unit, unit)


def _handle_api_exception(e: CephAPIException) -> JSONResponse:
    """Convert API exceptions to JSON responses.

    Args:
        e: CephAPIException to convert

    Returns:
        JSONResponse with error details
    """
    response_data = APIResponse(
        status="error",
        code=e.code,
        message=e.message,
        details=e.details,
    )
    return JSONResponse(
        status_code=e.status_code,
        content=response_data.model_dump(exclude_none=True),
    )


@router.post(
    "/fs/{name}/snapshot-schedule",
    response_model=APIResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add snapshot schedule",
    description="""
    Add a snapshot schedule for a CephFS filesystem path.

    Schedule format: <number><unit> where unit is:
    - h: hours (e.g., 1h, 6h)
    - d: days (e.g., 1d)
    - w: weeks (e.g., 1w)
    - M: months (e.g., 1M)
    - y: years (e.g., 1y)

    Retention policies can be specified to automatically clean up old snapshots.
    """,
    responses={
        201: {"description": "Snapshot schedule created successfully"},
        400: {"description": "Invalid schedule format"},
        404: {"description": "Filesystem not found"},
        500: {"description": "Ceph command failed"},
    },
)
async def add_snapshot_schedule(
    name: str,
    request: AddSnapshotScheduleRequest,
) -> JSONResponse:
    """Add a snapshot schedule to a CephFS filesystem.

    Args:
        name: Filesystem name
        request: Snapshot schedule configuration

    Returns:
        API response with created schedule details

    Raises:
        HTTPException: On unexpected errors
    """
    try:
        # Verify filesystem exists
        if not ceph_client.filesystem_exists(name):
            raise FilesystemNotFoundError(name)

        # Build base command
        cmd = ["fs", "snap-schedule", "add", request.path, request.schedule]

        # Add start time if provided
        if request.start_time:
            cmd.append(request.start_time)

        # Add filesystem parameter
        cmd.extend(["--fs", name])

        # Execute add schedule command
        logger.info(f"Adding snapshot schedule for {name}:{request.path} - {request.schedule}")
        ceph_client.execute_command(cmd)

        # Add retention policies if provided
        if request.retention:
            for unit, count in request.retention.model_dump(exclude_none=True).items():
                if count is not None:
                    retention_unit = _map_retention_unit(unit)
                    retention_cmd = [
                        "fs",
                        "snap-schedule",
                        "retention",
                        "add",
                        request.path,
                        retention_unit,
                        str(count),
                        "--fs",
                        name,
                    ]
                    logger.info(
                        f"Adding retention policy: {retention_unit}={count} for {name}:{request.path}"
                    )
                    ceph_client.execute_command(retention_cmd)

        # Create response
        response_data = AddSnapshotScheduleResponse(
            path=request.path,
            schedule=request.schedule,
            start_time=request.start_time,
            retention=request.retention,
            fs_name=name,
        )

        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=APIResponse(
                status="success",
                data=response_data.model_dump(exclude_none=True),
            ).model_dump(exclude_none=True),
        )

    except CephAPIException as e:
        logger.error(f"Failed to add snapshot schedule: {e.message}")
        return _handle_api_exception(e)
    except Exception as e:
        logger.exception(f"Unexpected error adding snapshot schedule: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}",
        )


@router.get(
    "/fs/{name}/snapshot-schedule",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
    summary="Get snapshot schedules",
    description="""
    Get all snapshot schedules for a CephFS filesystem path.

    Returns an empty list if no schedules are configured.
    """,
    responses={
        200: {"description": "Snapshot schedules retrieved successfully"},
        404: {"description": "Filesystem not found"},
        500: {"description": "Ceph command failed"},
    },
)
async def get_snapshot_schedules(
    name: str,
    path: str = Query(default="/", description="CephFS path to query"),
) -> JSONResponse:
    """Get snapshot schedules for a CephFS filesystem path.

    Args:
        name: Filesystem name
        path: CephFS path to query (default: "/")

    Returns:
        API response with list of schedules

    Raises:
        HTTPException: On unexpected errors
    """
    try:
        # Verify filesystem exists
        if not ceph_client.filesystem_exists(name):
            raise FilesystemNotFoundError(name)

        # Build command
        cmd = ["fs", "snap-schedule", "status", path, "--fs", name, "--format", "json"]

        # Execute command
        logger.info(f"Getting snapshot schedules for {name}:{path}")
        result = ceph_client.execute_command(cmd, parse_json=True)

        # Parse response - it's a list of schedule objects
        schedules: List[SnapshotScheduleInfo] = []
        if isinstance(result, list):
            for item in result:
                # Parse retention if present
                retention = None
                if "retention" in item and item["retention"]:
                    retention = item["retention"]

                schedules.append(
                    SnapshotScheduleInfo(
                        path=item.get("path", path),
                        schedule=item.get("schedule", ""),
                        retention=retention,
                        start=item.get("start"),
                        subvol=item.get("subvol"),
                    )
                )

        # Create response
        response_data = ListSnapshotSchedulesResponse(
            schedules=schedules,
            count=len(schedules),
            fs_name=name,
        )

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=APIResponse(
                status="success",
                data=response_data.model_dump(exclude_none=True),
            ).model_dump(exclude_none=True),
        )

    except CephCommandFailedError as e:
        # If no schedules exist, Ceph might return an error
        # Treat this as empty list
        if "not found" in e.details.get("stderr", "").lower():
            logger.info(f"No schedules found for {name}:{path}")
            response_data = ListSnapshotSchedulesResponse(
                schedules=[],
                count=0,
                fs_name=name,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=APIResponse(
                    status="success",
                    data=response_data.model_dump(exclude_none=True),
                ).model_dump(exclude_none=True),
            )
        logger.error(f"Failed to get snapshot schedules: {e.message}")
        return _handle_api_exception(e)
    except CephAPIException as e:
        logger.error(f"Failed to get snapshot schedules: {e.message}")
        return _handle_api_exception(e)
    except Exception as e:
        logger.exception(f"Unexpected error getting snapshot schedules: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}",
        )


@router.delete(
    "/fs/{name}/snapshot-schedule",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove snapshot schedule",
    description="""
    Remove a snapshot schedule from a CephFS filesystem path.

    If schedule is provided, only that specific schedule is removed.
    If schedule is omitted, all schedules on the path are removed.
    """,
    responses={
        204: {"description": "Snapshot schedule removed successfully"},
        404: {"description": "Filesystem or schedule not found"},
        500: {"description": "Ceph command failed"},
    },
)
async def remove_snapshot_schedule(
    name: str,
    path: str = Query(default="/", description="CephFS path"),
    schedule: Union[str, None] = Query(
        default=None,
        description="Specific schedule to remove (omit to remove all)",
    ),
) -> JSONResponse:
    """Remove a snapshot schedule from a CephFS filesystem path.

    Args:
        name: Filesystem name
        path: CephFS path (default: "/")
        schedule: Specific schedule to remove (optional)

    Returns:
        204 No Content on success

    Raises:
        HTTPException: On unexpected errors
    """
    try:
        # Verify filesystem exists
        if not ceph_client.filesystem_exists(name):
            raise FilesystemNotFoundError(name)

        # Build command
        cmd = ["fs", "snap-schedule", "remove", path]

        # Add specific schedule if provided
        if schedule:
            cmd.append(schedule)

        # Add filesystem parameter
        cmd.extend(["--fs", name])

        # Execute command
        logger.info(f"Removing snapshot schedule for {name}:{path} schedule={schedule}")
        ceph_client.execute_command(cmd)

        return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)

    except CephCommandFailedError as e:
        # Check if it's a "not found" error
        stderr = e.details.get("stderr", "").lower()
        if "not found" in stderr or "does not exist" in stderr:
            logger.error(f"Schedule not found: {name}:{path} schedule={schedule}")
            raise_error = SnapshotScheduleNotFoundError(path=path, schedule=schedule)
            return _handle_api_exception(raise_error)
        logger.error(f"Failed to remove snapshot schedule: {e.message}")
        return _handle_api_exception(e)
    except CephAPIException as e:
        logger.error(f"Failed to remove snapshot schedule: {e.message}")
        return _handle_api_exception(e)
    except Exception as e:
        logger.exception(f"Unexpected error removing snapshot schedule: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}",
        )


@router.get(
    "/fs/{name}/snapshots",
    response_model=APIResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    summary="List snapshots (Not Implemented)",
    description="""
    List snapshots in a CephFS filesystem path.

    This endpoint is not yet implemented and will be available in Phase 2.
    Implementation requires mounting the filesystem or using libcephfs to
    access the .snap directory.
    """,
    responses={
        501: {"description": "Not implemented - available in Phase 2"},
    },
)
async def list_snapshots(
    name: str,
    path: str = Query(default="/", description="CephFS path to query"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum snapshots to return"),
    recursive: bool = Query(default=False, description="Search recursively"),
) -> JSONResponse:
    """List snapshots in a CephFS filesystem path.

    This endpoint is not yet implemented. It requires either:
    1. Mounting the CephFS filesystem and reading .snap directories
    2. Using libcephfs Python bindings to access snapshot metadata
    3. Using Ceph MDS admin commands (if available)

    Args:
        name: Filesystem name
        path: CephFS path to query
        limit: Maximum number of snapshots to return
        recursive: Whether to search recursively

    Returns:
        501 Not Implemented response
    """
    logger.info(
        f"List snapshots requested for {name}:{path} (limit={limit}, recursive={recursive})"
    )

    response_data = APIResponse(
        status="error",
        code="NOT_IMPLEMENTED",
        message="Snapshot listing is not yet implemented",
        details={
            "reason": "This feature requires filesystem mounting or libcephfs integration",
            "planned_for": "Phase 2",
            "alternatives": [
                "Use 'ceph fs snap-schedule status' to view scheduled snapshots",
                "Mount the filesystem and access .snap directories directly",
                "Use 'ls -la <mount>/.snap/' to view snapshots",
            ],
            "requested_params": {
                "fs_name": name,
                "path": path,
                "limit": limit,
                "recursive": recursive,
            },
        },
    )

    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=response_data.model_dump(exclude_none=True),
    )
