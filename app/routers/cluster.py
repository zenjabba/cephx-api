"""Cluster information endpoints."""

import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Annotated, Any, Callable, Dict, List

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
        self.value = value
        self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at


_cache: Dict[str, CacheEntry] = {}


def ttl_cache(ttl_seconds: int) -> Callable:
    """Decorator to cache function results with TTL."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            if cache_key in _cache:
                entry = _cache[cache_key]
                if not entry.is_expired():
                    logger.debug(f"Cache hit for {func.__name__}")
                    return entry.value
                else:
                    del _cache[cache_key]
            result = await func(*args, **kwargs)
            _cache[cache_key] = CacheEntry(result, ttl_seconds)
            return result
        return wrapper
    return decorator


async def require_cluster_read(
    auth: Annotated[AuthContext, Depends(verify_api_key)],
) -> AuthContext:
    auth.require_permission("cluster:read")
    return auth


@router.get("/monitors", response_model=APIResponse)
@ttl_cache(ttl_seconds=300)
async def get_monitors(
    auth: Annotated[AuthContext, Depends(require_cluster_read)],
) -> Dict[str, Any]:
    """Get monitor addresses."""
    try:
        # Use ceph mon dump to get full monitor info
        mon_data = ceph_client.execute_command(
            ["mon", "dump", "--format", "json"],
            parse_json=True,
        )

        monitors = []
        for mon in mon_data.get("mons", []):
            # Get the v1 address (port 6789)
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

    except Exception as e:
        logger.exception("Error getting monitors")
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:monitors",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )
        return {
            "status": "error",
            "code": "CEPH_COMMAND_FAILED",
            "message": str(e),
            "details": {},
        }


@router.get("/status", response_model=APIResponse)
@ttl_cache(ttl_seconds=30)
async def get_cluster_status(
    auth: Annotated[AuthContext, Depends(require_cluster_read)],
) -> Dict[str, Any]:
    """Get cluster status."""
    try:
        status_data = ceph_client.execute_command(
            ["status", "--format", "json"],
            parse_json=True,
        )

        # Health
        health = status_data.get("health", {}).get("status", "UNKNOWN")

        # Monitor status - monmap.num_mons is at root level in newer Ceph
        monmap = status_data.get("monmap", {})
        mon_status = MonStatus(
            epoch=monmap.get("epoch", 0),
            num_mons=monmap.get("num_mons", 0),
            quorum=status_data.get("quorum", []),
        )

        # OSD status - osdmap is directly at root level (not nested) in newer Ceph
        osdmap = status_data.get("osdmap", {})
        # Handle both old nested format and new flat format
        if "osdmap" in osdmap:
            osdmap = osdmap["osdmap"]
        
        osd_status = OSDStatus(
            num_osds=osdmap.get("num_osds", 0),
            num_up_osds=osdmap.get("num_up_osds", 0),
            num_in_osds=osdmap.get("num_in_osds", 0),
        )

        # PG status
        pgmap = status_data.get("pgmap", {})
        num_pgs = pgmap.get("num_pgs", 0)
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

    except Exception as e:
        logger.exception("Error getting cluster status")
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:status",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )
        return {
            "status": "error",
            "code": "CEPH_COMMAND_FAILED",
            "message": str(e),
            "details": {},
        }


@router.get("/df", response_model=APIResponse)
@ttl_cache(ttl_seconds=30)
async def get_cluster_df(
    auth: Annotated[AuthContext, Depends(require_cluster_read)],
) -> Dict[str, Any]:
    """Get cluster disk usage."""
    try:
        df_data = ceph_client.get_cluster_df()

        stats_raw = df_data.get("stats", {})
        cluster_stats = ClusterStats(
            total_bytes=stats_raw.get("total_bytes", 0),
            total_used_bytes=stats_raw.get("total_used_bytes", 0),
            total_avail_bytes=stats_raw.get("total_avail_bytes", 0),
        )

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

        audit_logger.log_operation(
            operation="READ",
            resource="cluster:df",
            user=auth.user,
            status="SUCCESS",
            details={"pool_count": len(pools)},
        )

        return {
            "status": "success",
            "data": response_data.model_dump(),
        }

    except Exception as e:
        logger.exception("Error getting cluster df")
        audit_logger.log_operation(
            operation="READ",
            resource="cluster:df",
            user=auth.user,
            status="FAILED",
            details={"error": str(e)},
        )
        return {
            "status": "error",
            "code": "CEPH_COMMAND_FAILED",
            "message": str(e),
            "details": {},
        }
