"""Cluster information endpoints."""

import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Annotated, Any, Callable, Dict

from fastapi import APIRouter, Depends

from app.core.auth import AuthContext, verify_api_key
from app.core.exceptions import CephAPIException, CephCommandFailedError
from app.core.logging import audit_logger
from app.models.cluster import (
    APIResponse,
    ClusterDfData,
    ClusterStats,
    ClusterStatusData,
    MonitorsResponse,
    MonStatus,
    MonitorInfo,
    OSDStatus,
    PGStatus,
    PoolInfo,
    PoolStats,
)
from app.services.ceph_client import ceph_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Cluster"])


# Simple TTL cache implementation
class CacheEntry:
    """Cache entry with TTL."""

    def __init__(self, value: Any, ttl_seconds: int) -> None:
        """Initialize cache entry.

        Args:
            value: Cached value
            ttl_seconds: Time to live in seconds
        """
        self.value = value
        self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    def is_expired(self) -> bool:
        """Check if cache entry is expired."""
        return datetime.now(timezone.utc) > self.expires_at


# Cache storage
_cache: Dict[str, CacheEntry] = {}


def ttl_cache(ttl_seconds: int) -> Callable:
    """Decorator to cache function results with TTL.

    Args:
        ttl_seconds: Time to live in seconds

    Returns:
        Decorator function
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Create cache key from function name and arguments
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

            # Check if cached value exists and is not expired
            if cache_key in _cache:
                entry = _cache[cache_key]
                if not entry.is_expired():
                    logger.debug(f"Cache hit for {func.__name__}")
                    return entry.value
                else:
                    logger.debug(f"Cache expired for {func.__name__}")
                    del _cache[cache_key]

            # Call function and cache result
            logger.debug(f"Cache miss for {func.__name__}")
            result = await func(*args, **kwargs)
            _cache[cache_key] = CacheEntry(result, ttl_seconds)
            return result

        return wrapper

    return decorator


async def require_cluster_read(
    auth: Annotated[AuthContext, Depends(verify_api_key)],
) -> AuthContext:
    """Dependency that requires cluster:read permission.

    Args:
        auth: Authentication context

    Returns:
        Authentication context

    Raises:
        PermissionDeniedError: If user lacks cluster:read permission
    """
    auth.require_permission("cluster:read")
    return auth


@router.get("/monitors", response_model=APIResponse)
@ttl_cache(ttl_seconds=300)  # Cache for 5 minutes
async def get_monitors(
    auth: Annotated[AuthContext, Depends(require_cluster_read)],
) -> Dict[str, Any]:
    """Get monitor addresses and information.

    This endpoint retrieves the list of Ceph monitors in the cluster,
    including their addresses and ranks.

    Args:
        auth: Authentication context (injected)

    Returns:
        APIResponse with monitors data containing:
        - monitors: List of monitor objects with name, addr, and rank
        - total: Total number of monitors

    Raises:
        CephClusterUnavailable: If cannot connect to Ceph cluster
        CephCommandFailedError: If Ceph command fails
    """
    try:
        # Execute ceph status command
        status_data = ceph_client.execute_command(
            ["status", "--format", "json"],
            parse_json=True,
        )

        # Extract monitor information
        monmap = status_data.get("monmap", {})
        mons_data = monmap.get("mons", [])

        monitors = []
        for mon in mons_data:
            # Parse addr format: "10.10.1.1:6789/0" -> "10.10.1.1:6789"
            addr = mon.get("addr", "")
            if "/" in addr:
                addr = addr.split("/")[0]

            monitors.append(
                MonitorInfo(
                    name=mon.get("name", ""),
                    addr=addr,
                    rank=mon.get("rank", 0),
                )
            )

        response_data = MonitorsResponse(
            monitors=monitors,
            total=len(monitors),
        )

        # Log audit entry
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:monitors",
            user=auth.user,
            status="SUCCESS",
            details={"monitor_count": len(monitors)},
        )

        return {
            "status": "success",
            "data": response_data.model_dump(),
        }

    except CephCommandFailedError as e:
        logger.error(f"Failed to get monitor information: {e}")
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:monitors",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )

        # Check if cluster is unavailable
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            return {
                "status": "error",
                "code": "CEPH_CLUSTER_UNAVAILABLE",
                "message": "Ceph cluster is unavailable",
                "details": e.details,
            }

        return {
            "status": "error",
            "code": "CEPH_COMMAND_FAILED",
            "message": "Failed to retrieve monitor information",
            "details": e.details,
        }

    except Exception as e:
        logger.exception("Unexpected error getting monitors")
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:monitors",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )

        return {
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "details": {"error": str(e)},
        }


@router.get("/status", response_model=APIResponse)
@ttl_cache(ttl_seconds=30)  # Cache for 30 seconds
async def get_cluster_status(
    auth: Annotated[AuthContext, Depends(require_cluster_read)],
) -> Dict[str, Any]:
    """Get cluster status information.

    This endpoint retrieves comprehensive cluster status including health,
    monitor status, OSD status, and placement group status.

    Args:
        auth: Authentication context (injected)

    Returns:
        APIResponse with cluster status data containing:
        - health: Cluster health (HEALTH_OK, HEALTH_WARN, HEALTH_ERR)
        - mon_status: Monitor status with epoch, count, and quorum
        - osd_status: OSD counts (total, up, in)
        - pg_status: Placement group counts (total, active+clean)

    Raises:
        CephClusterUnavailable: If cannot connect to Ceph cluster
        CephCommandFailedError: If Ceph command fails
    """
    try:
        # Execute ceph status command
        status_data = ceph_client.execute_command(
            ["status", "--format", "json"],
            parse_json=True,
        )

        # Extract health status
        health = status_data.get("health", {}).get("status", "UNKNOWN")

        # Extract monitor status
        monmap = status_data.get("monmap", {})
        mon_status = MonStatus(
            epoch=monmap.get("epoch", 0),
            num_mons=len(monmap.get("mons", [])),
            quorum=status_data.get("quorum", []),
        )

        # Extract OSD status
        osdmap = status_data.get("osdmap", {}).get("osdmap", {})
        osd_status = OSDStatus(
            num_osds=osdmap.get("num_osds", 0),
            num_up_osds=osdmap.get("num_up_osds", 0),
            num_in_osds=osdmap.get("num_in_osds", 0),
        )

        # Extract PG status
        pgmap = status_data.get("pgmap", {})
        num_pgs = pgmap.get("num_pgs", 0)

        # Count active+clean PGs
        num_active_clean = 0
        for pg_state in pgmap.get("pgs_by_state", []):
            if pg_state.get("state_name") == "active+clean":
                num_active_clean = pg_state.get("count", 0)
                break

        pg_status = PGStatus(
            num_pgs=num_pgs,
            num_active_clean=num_active_clean,
        )

        response_data = ClusterStatusData(
            health=health,
            mon_status=mon_status,
            osd_status=osd_status,
            pg_status=pg_status,
        )

        # Log audit entry
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:status",
            user=auth.user,
            status="SUCCESS",
            details={"health": health},
        )

        return {
            "status": "success",
            "data": response_data.model_dump(),
        }

    except CephCommandFailedError as e:
        logger.error(f"Failed to get cluster status: {e}")
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:status",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )

        # Check if cluster is unavailable
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            return {
                "status": "error",
                "code": "CEPH_CLUSTER_UNAVAILABLE",
                "message": "Ceph cluster is unavailable",
                "details": e.details,
            }

        return {
            "status": "error",
            "code": "CEPH_COMMAND_FAILED",
            "message": "Failed to retrieve cluster status",
            "details": e.details,
        }

    except Exception as e:
        logger.exception("Unexpected error getting cluster status")
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:status",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )

        return {
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "details": {"error": str(e)},
        }


@router.get("/df", response_model=APIResponse)
@ttl_cache(ttl_seconds=30)  # Cache for 30 seconds
async def get_cluster_df(
    auth: Annotated[AuthContext, Depends(require_cluster_read)],
) -> Dict[str, Any]:
    """Get cluster disk usage statistics.

    This endpoint retrieves detailed cluster storage statistics including
    global usage and per-pool statistics.

    Args:
        auth: Authentication context (injected)

    Returns:
        APIResponse with cluster df data containing:
        - stats: Global cluster statistics (total, used, available bytes)
        - pools: List of pool objects with name, id, and detailed stats

    Raises:
        CephClusterUnavailable: If cannot connect to Ceph cluster
        CephCommandFailedError: If Ceph command fails
    """
    try:
        # Execute ceph df detail command
        df_data = ceph_client.get_cluster_df()

        # Extract global stats
        stats_raw = df_data.get("stats", {})
        cluster_stats = ClusterStats(
            total_bytes=stats_raw.get("total_bytes", 0),
            total_used_bytes=stats_raw.get("total_used_bytes", 0),
            total_avail_bytes=stats_raw.get("total_avail_bytes", 0),
        )

        # Extract pool stats
        pools = []
        for pool_data in df_data.get("pools", []):
            pool_stats_raw = pool_data.get("stats", {})

            pool_stats = PoolStats(
                stored=pool_stats_raw.get("stored", 0),
                objects=pool_stats_raw.get("objects", 0),
                kb_used=pool_stats_raw.get("kb_used", 0),
                bytes_used=pool_stats_raw.get("bytes_used", 0),
                percent_used=pool_stats_raw.get("percent_used", 0.0),
            )

            pools.append(
                PoolInfo(
                    name=pool_data.get("name", ""),
                    id=pool_data.get("id", 0),
                    stats=pool_stats,
                )
            )

        response_data = ClusterDfData(
            stats=cluster_stats,
            pools=pools,
        )

        # Log audit entry
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:df",
            user=auth.user,
            status="SUCCESS",
            details={
                "pool_count": len(pools),
                "total_bytes": cluster_stats.total_bytes,
            },
        )

        return {
            "status": "success",
            "data": response_data.model_dump(),
        }

    except CephCommandFailedError as e:
        logger.error(f"Failed to get cluster df: {e}")
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:df",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )

        # Check if cluster is unavailable
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            return {
                "status": "error",
                "code": "CEPH_CLUSTER_UNAVAILABLE",
                "message": "Ceph cluster is unavailable",
                "details": e.details,
            }

        return {
            "status": "error",
            "code": "CEPH_COMMAND_FAILED",
            "message": "Failed to retrieve cluster disk usage",
            "details": e.details,
        }

    except Exception as e:
        logger.exception("Unexpected error getting cluster df")
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:df",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )

        return {
            "status": "error",
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred",
            "details": {"error": str(e)},
        }
