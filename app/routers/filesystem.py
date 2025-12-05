"""CephFS filesystem management endpoints."""

import logging
from typing import Annotated, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import AuthContext, require_fs_read, require_fs_write
from app.core.exceptions import (
    CephAPIException,
    CephCommandFailedError,
    ConfirmationRequiredError,
    FilesystemAlreadyExistsError,
    FilesystemNotFoundError,
    InvalidCrushRuleError,
)
from app.core.logging import audit_logger
from app.models.filesystem import (
    APIResponse,
    CreateFilesystemRequest,
    CreateFilesystemResponse,
    FilesystemInfo,
    FilesystemUsageResponse,
    FilesystemUsageStats,
    FilesystemWithUsage,
    ListFilesystemsResponse,
)
from app.services.ceph_client import ceph_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Filesystems"])


def _get_pool_usage(pool_name: str, df_data: dict) -> Union[FilesystemUsageStats, None]:
    """Extract usage statistics for a specific pool.

    Args:
        pool_name: Name of the pool
        df_data: Output from 'ceph df detail --format json'

    Returns:
        FilesystemUsageStats if pool found, None otherwise
    """
    pools = df_data.get("pools", [])

    for pool in pools:
        if pool.get("name") == pool_name:
            stats = pool.get("stats", {})
            stored = stats.get("stored", 0)
            used = stats.get("bytes_used", 0)
            objects = stats.get("objects", 0)
            percent_used = stats.get("percent_used", 0.0)

            # Calculate TB from bytes (1 TB = 1024^4 bytes)
            stored_tb = round(stored / (1024**4), 3)

            return FilesystemUsageStats(
                stored_bytes=stored,
                stored_tb=stored_tb,
                used_bytes=used,
                objects=objects,
                percent_used=percent_used,
            )

    return None


def _rollback_filesystem_creation(
    name: str,
    meta_pool: str,
    data_pool: str,
    created_meta: bool,
    created_data: bool,
    created_fs: bool,
    created_auth: bool,
    auth_client_name: Union[str, None],
) -> None:
    """Rollback filesystem creation on failure.

    Args:
        name: Filesystem name
        meta_pool: Metadata pool name
        data_pool: Data pool name
        created_meta: Whether metadata pool was created
        created_data: Whether data pool was created
        created_fs: Whether filesystem was created
        created_auth: Whether auth was created
        auth_client_name: Client name for auth
    """
    logger.warning(f"Rolling back filesystem creation for '{name}'")

    try:
        # Remove filesystem if created
        if created_fs:
            logger.info(f"Removing filesystem '{name}'")
            ceph_client.remove_filesystem(name)

        # Remove auth if created
        if created_auth and auth_client_name:
            logger.info(f"Removing auth for client '{auth_client_name}'")
            ceph_client.delete_auth_client(auth_client_name)

        # Remove pools if created
        if created_data:
            logger.info(f"Removing data pool '{data_pool}'")
            ceph_client.delete_pool(data_pool)

        if created_meta:
            logger.info(f"Removing metadata pool '{meta_pool}'")
            ceph_client.delete_pool(meta_pool)

    except Exception as e:
        logger.error(f"Error during rollback: {e}")


@router.post(
    "/fs",
    response_model=APIResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create CephFS Filesystem",
    description="Create a new CephFS filesystem with metadata and data pools",
)
async def create_filesystem(
    request: CreateFilesystemRequest,
    auth: Annotated[AuthContext, Depends(require_fs_write)],
) -> APIResponse:
    """Create a new CephFS filesystem.

    Creates metadata and data pools, initializes the filesystem,
    optionally enables snapshots, and creates client authentication.

    Args:
        request: Filesystem creation parameters
        auth: Authentication context

    Returns:
        APIResponse with filesystem details and auth key

    Raises:
        HTTPException: On validation or execution errors
    """
    # Track what we've created for rollback
    created_meta = False
    created_data = False
    created_fs = False
    created_auth = False

    meta_pool = f"cephfs.{request.name}.meta"
    data_pool = f"cephfs.{request.name}.data"
    auth_client_name = request.auth_client_name or request.name

    try:
        # Check if filesystem already exists
        if ceph_client.filesystem_exists(request.name):
            raise FilesystemAlreadyExistsError(
                request.name,
                {"metadata_pool": meta_pool, "data_pool": data_pool},
            )

        # Validate CRUSH rule exists
        if not ceph_client.crush_rule_exists(request.crush_rule):
            raise InvalidCrushRuleError(request.crush_rule)

        # Check if pools already exist
        if ceph_client.pool_exists(meta_pool):
            raise FilesystemAlreadyExistsError(
                request.name,
                {"reason": f"Metadata pool '{meta_pool}' already exists"},
            )

        if ceph_client.pool_exists(data_pool):
            raise FilesystemAlreadyExistsError(
                request.name,
                {"reason": f"Data pool '{data_pool}' already exists"},
            )

        logger.info(f"Creating filesystem '{request.name}' for user '{auth.user}'")

        # Step 1: Create metadata pool
        logger.info(f"Creating metadata pool '{meta_pool}'")
        ceph_client.create_pool(
            pool_name=meta_pool,
            pg_num=request.meta_pool_pg,
            pool_type="replicated",
            crush_rule=request.crush_rule,
        )
        created_meta = True

        # Step 2: Create data pool
        logger.info(f"Creating data pool '{data_pool}'")
        ceph_client.create_pool(
            pool_name=data_pool,
            pg_num=request.meta_pool_pg,  # Use same PG count
            pool_type=request.data_pool_type,
            crush_rule=request.crush_rule,
        )
        created_data = True

        # Step 3: Create filesystem
        logger.info(f"Creating filesystem '{request.name}'")
        ceph_client.create_filesystem(
            name=request.name,
            meta_pool=meta_pool,
            data_pool=data_pool,
        )
        created_fs = True

        # Step 4: Enable snapshots if requested
        if request.enable_snapshots:
            logger.info(f"Enabling snapshots for '{request.name}'")
            ceph_client.set_filesystem_flag(
                name=request.name,
                flag="allow_new_snaps",
                value=True,
            )

        # Step 5: Create client auth if requested
        auth_key = None
        if request.create_auth:
            logger.info(
                f"Creating auth for client '{auth_client_name}' on '{request.name}'"
            )
            auth_key = ceph_client.authorize_filesystem_client(
                filesystem=request.name,
                client_name=auth_client_name,
                path="/",
                permissions="rw",
            )
            created_auth = True

        # Log successful operation
        audit_logger.log_operation(
            operation="CREATE",
            resource=f"filesystem:{request.name}",
            user=auth.user,
            status="SUCCESS",
            details={
                "metadata_pool": meta_pool,
                "data_pool": data_pool,
                "crush_rule": request.crush_rule,
                "snapshots_enabled": request.enable_snapshots,
                "auth_created": request.create_auth,
            },
        )

        response_data = CreateFilesystemResponse(
            name=request.name,
            metadata_pool=meta_pool,
            data_pool=data_pool,
            snapshots_enabled=request.enable_snapshots,
            auth_created=request.create_auth,
            auth_client_name=auth_client_name if request.create_auth else None,
            auth_key=auth_key,
        )

        return APIResponse(status="success", data=response_data.model_dump())

    except CephAPIException:
        # Rollback on any Ceph API exception
        _rollback_filesystem_creation(
            name=request.name,
            meta_pool=meta_pool,
            data_pool=data_pool,
            created_meta=created_meta,
            created_data=created_data,
            created_fs=created_fs,
            created_auth=created_auth,
            auth_client_name=auth_client_name,
        )

        # Log failed operation
        audit_logger.log_operation(
            operation="CREATE",
            resource=f"filesystem:{request.name}",
            user=auth.user,
            status="FAILED",
        )

        raise

    except Exception as e:
        # Rollback on unexpected errors
        _rollback_filesystem_creation(
            name=request.name,
            meta_pool=meta_pool,
            data_pool=data_pool,
            created_meta=created_meta,
            created_data=created_data,
            created_fs=created_fs,
            created_auth=created_auth,
            auth_client_name=auth_client_name,
        )

        logger.error(f"Unexpected error creating filesystem: {e}")

        audit_logger.log_operation(
            operation="CREATE",
            resource=f"filesystem:{request.name}",
            user=auth.user,
            status="FAILED",
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error: {str(e)}",
        ) from e


@router.get(
    "/fs/{name}",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Filesystem Info",
    description="Retrieve detailed information about a specific filesystem",
)
async def get_filesystem(
    name: str,
    auth: Annotated[AuthContext, Depends(require_fs_read)],
) -> APIResponse:
    """Get information about a specific filesystem.

    Args:
        name: Filesystem name
        auth: Authentication context

    Returns:
        APIResponse with filesystem details

    Raises:
        HTTPException: If filesystem not found
    """
    try:
        logger.info(f"Getting info for filesystem '{name}'")

        # Get filesystem info
        fs_info = ceph_client.get_filesystem_info(name)

        # Get list of filesystems to extract additional info
        fs_list = ceph_client.list_filesystems()
        fs_data = next((fs for fs in fs_list if fs.get("name") == name), None)

        if not fs_data:
            raise FilesystemNotFoundError(name)

        # Build response
        response_data = FilesystemInfo(
            name=fs_data.get("name", name),
            metadata_pool=fs_data.get("metadata_pool", ""),
            data_pools=fs_data.get("data_pools", []),
            mds_count=fs_data.get("mds_count", 0),
        )

        audit_logger.log_operation(
            operation="READ",
            resource=f"filesystem:{name}",
            user=auth.user,
            status="SUCCESS",
        )

        return APIResponse(status="success", data=response_data.model_dump())

    except FilesystemNotFoundError:
        audit_logger.log_operation(
            operation="READ",
            resource=f"filesystem:{name}",
            user=auth.user,
            status="FAILED",
        )
        raise


@router.get(
    "/fs/{name}/usage",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Filesystem Usage",
    description="Retrieve usage statistics for a filesystem (stored bytes for billing)",
)
async def get_filesystem_usage(
    name: str,
    auth: Annotated[AuthContext, Depends(require_fs_read)],
) -> APIResponse:
    """Get usage statistics for a filesystem.

    Returns stored_bytes (before replication) for accurate billing.

    Args:
        name: Filesystem name
        auth: Authentication context

    Returns:
        APIResponse with usage statistics

    Raises:
        HTTPException: If filesystem not found
    """
    try:
        logger.info(f"Getting usage for filesystem '{name}'")

        # Get filesystem info to find data pool
        fs_list = ceph_client.list_filesystems()
        fs_data = next((fs for fs in fs_list if fs.get("name") == name), None)

        if not fs_data:
            raise FilesystemNotFoundError(name)

        # Get cluster df data
        df_data = ceph_client.get_cluster_df()

        # Extract data pool name (use first data pool)
        data_pools = fs_data.get("data_pools", [])
        if not data_pools:
            raise CephCommandFailedError(
                command=f"get filesystem usage for {name}",
                exit_code=1,
                stderr="No data pools found for filesystem",
            )

        data_pool = data_pools[0]

        # Get pool usage
        usage = _get_pool_usage(data_pool, df_data)

        if not usage:
            raise CephCommandFailedError(
                command=f"get pool usage for {data_pool}",
                exit_code=1,
                stderr=f"Pool '{data_pool}' not found in df output",
            )

        response_data = FilesystemUsageResponse(
            name=name,
            usage=usage,
        )

        audit_logger.log_operation(
            operation="READ",
            resource=f"filesystem:{name}/usage",
            user=auth.user,
            status="SUCCESS",
        )

        return APIResponse(status="success", data=response_data.model_dump())

    except FilesystemNotFoundError:
        audit_logger.log_operation(
            operation="READ",
            resource=f"filesystem:{name}/usage",
            user=auth.user,
            status="FAILED",
        )
        raise


@router.get(
    "/fs",
    response_model=APIResponse,
    status_code=status.HTTP_200_OK,
    summary="List Filesystems",
    description="List all CephFS filesystems with optional usage statistics",
)
async def list_filesystems(
    auth: Annotated[AuthContext, Depends(require_fs_read)],
    include_usage: Annotated[bool, Query(description="Include usage statistics")] = False,
) -> APIResponse:
    """List all CephFS filesystems.

    Args:
        include_usage: Whether to include usage statistics
        auth: Authentication context

    Returns:
        APIResponse with list of filesystems

    Raises:
        HTTPException: On execution errors
    """
    try:
        logger.info(f"Listing filesystems (include_usage={include_usage})")

        # Get filesystem list
        fs_list = ceph_client.list_filesystems()

        # Get usage data if requested
        df_data = None
        if include_usage:
            df_data = ceph_client.get_cluster_df()

        # Build response
        filesystems = []
        for fs_data in fs_list:
            fs_info = FilesystemWithUsage(
                name=fs_data.get("name", ""),
                metadata_pool=fs_data.get("metadata_pool", ""),
                data_pools=fs_data.get("data_pools", []),
                mds_count=fs_data.get("mds_count", 0),
            )

            # Add usage if requested
            if include_usage and df_data:
                data_pools = fs_data.get("data_pools", [])
                if data_pools:
                    usage = _get_pool_usage(data_pools[0], df_data)
                    fs_info.usage = usage

            filesystems.append(fs_info)

        response_data = ListFilesystemsResponse(
            filesystems=filesystems,
            count=len(filesystems),
        )

        audit_logger.log_operation(
            operation="READ",
            resource="filesystem:*",
            user=auth.user,
            status="SUCCESS",
            details={"include_usage": include_usage, "count": len(filesystems)},
        )

        return APIResponse(status="success", data=response_data.model_dump())

    except CephCommandFailedError:
        audit_logger.log_operation(
            operation="READ",
            resource="filesystem:*",
            user=auth.user,
            status="FAILED",
        )
        raise


@router.delete(
    "/fs/{name}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Filesystem",
    description="Delete a CephFS filesystem and optionally its client auth",
)
async def delete_filesystem(
    name: str,
    auth: Annotated[AuthContext, Depends(require_fs_write)],
    confirm: Annotated[str, Query(description="Must equal filesystem name to confirm deletion")],
    delete_auth: Annotated[bool, Query(description="Delete client auth")] = True,
) -> None:
    """Delete a CephFS filesystem.

    Requires confirmation by passing the filesystem name in the confirm parameter.

    Args:
        name: Filesystem name
        confirm: Confirmation string (must equal name)
        delete_auth: Whether to delete client auth
        auth: Authentication context

    Raises:
        HTTPException: On validation or execution errors
    """
    try:
        # Validate confirmation
        if confirm != name:
            raise ConfirmationRequiredError(
                f"Confirmation failed. Query parameter 'confirm' must equal '{name}'",
                {"provided": confirm, "required": name},
            )

        logger.info(f"Deleting filesystem '{name}' for user '{auth.user}'")

        # Check if filesystem exists
        if not ceph_client.filesystem_exists(name):
            raise FilesystemNotFoundError(name)

        # Delete client auth if requested
        if delete_auth:
            logger.info(f"Deleting auth for client '{name}'")
            ceph_client.delete_auth_client(name)

        # Remove filesystem
        logger.info(f"Removing filesystem '{name}'")
        ceph_client.remove_filesystem(name)

        audit_logger.log_operation(
            operation="DELETE",
            resource=f"filesystem:{name}",
            user=auth.user,
            status="SUCCESS",
            details={"delete_auth": delete_auth},
        )

    except (FilesystemNotFoundError, ConfirmationRequiredError):
        audit_logger.log_operation(
            operation="DELETE",
            resource=f"filesystem:{name}",
            user=auth.user,
            status="FAILED",
        )
        raise

    except CephCommandFailedError:
        audit_logger.log_operation(
            operation="DELETE",
            resource=f"filesystem:{name}",
            user=auth.user,
            status="FAILED",
        )
        raise
