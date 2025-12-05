#!/usr/bin/env python3
"""Example client for Ceph cluster API endpoints."""

import sys
from typing import Any

import requests


class CephClusterAPIClient:
    """Client for interacting with Ceph cluster API."""

    def __init__(self, base_url: str, api_key: str) -> None:
        """Initialize client.

        Args:
            base_url: Base URL of the API (e.g., http://localhost:8080)
            api_key: API key for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.headers = {"X-API-Key": api_key}

    def _make_request(self, endpoint: str) -> dict[str, Any]:
        """Make API request and handle errors.

        Args:
            endpoint: API endpoint path

        Returns:
            Response data

        Raises:
            SystemExit: If request fails
        """
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error: {e}", file=sys.stderr)
            if response.text:
                print(f"Response: {response.text}", file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(f"Request Error: {e}", file=sys.stderr)
            sys.exit(1)

    def get_monitors(self) -> dict[str, Any]:
        """Get cluster monitor information.

        Returns:
            Monitor data including list of monitors and total count
        """
        return self._make_request("/api/v1/cluster/monitors")

    def get_status(self) -> dict[str, Any]:
        """Get cluster status.

        Returns:
            Cluster status including health, monitor, OSD, and PG status
        """
        return self._make_request("/api/v1/cluster/status")

    def get_df(self) -> dict[str, Any]:
        """Get cluster disk usage statistics.

        Returns:
            Cluster df data including global stats and per-pool statistics
        """
        return self._make_request("/api/v1/cluster/df")


def format_bytes(bytes_value: int) -> str:
    """Format bytes into human-readable string.

    Args:
        bytes_value: Number of bytes

    Returns:
        Formatted string (e.g., "1.5 TB")
    """
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} EB"


def main() -> None:
    """Main function demonstrating API usage."""
    # Initialize client
    client = CephClusterAPIClient(
        base_url="http://localhost:8080",
        api_key="admin-key",
    )

    print("=" * 80)
    print("Ceph Cluster Information")
    print("=" * 80)
    print()

    # Get and display monitor information
    print("Monitor Information:")
    print("-" * 80)
    monitors_response = client.get_monitors()
    if monitors_response["status"] == "success":
        monitors_data = monitors_response["data"]
        print(f"Total Monitors: {monitors_data['total']}")
        print()
        for mon in monitors_data["monitors"]:
            print(f"  - {mon['name']}: {mon['addr']} (rank {mon['rank']})")
    else:
        print(f"Error: {monitors_response.get('message', 'Unknown error')}")
    print()

    # Get and display cluster status
    print("Cluster Status:")
    print("-" * 80)
    status_response = client.get_status()
    if status_response["status"] == "success":
        status_data = status_response["data"]

        # Health
        health = status_data["health"]
        health_color = {
            "HEALTH_OK": "✓",
            "HEALTH_WARN": "⚠",
            "HEALTH_ERR": "✗",
        }.get(health, "?")
        print(f"Health: {health_color} {health}")
        print()

        # Monitors
        mon_status = status_data["mon_status"]
        print(f"Monitors:")
        print(f"  - Count: {mon_status['num_mons']}")
        print(f"  - Epoch: {mon_status['epoch']}")
        print(f"  - Quorum: {mon_status['quorum']}")
        print()

        # OSDs
        osd_status = status_data["osd_status"]
        print(f"OSDs:")
        print(f"  - Total: {osd_status['num_osds']}")
        print(f"  - Up: {osd_status['num_up_osds']}")
        print(f"  - In: {osd_status['num_in_osds']}")
        print()

        # PGs
        pg_status = status_data["pg_status"]
        print(f"Placement Groups:")
        print(f"  - Total: {pg_status['num_pgs']}")
        print(f"  - Active+Clean: {pg_status['num_active_clean']}")
        if pg_status["num_pgs"] > 0:
            clean_pct = (pg_status["num_active_clean"] / pg_status["num_pgs"]) * 100
            print(f"  - Clean Percentage: {clean_pct:.2f}%")
    else:
        print(f"Error: {status_response.get('message', 'Unknown error')}")
    print()

    # Get and display cluster disk usage
    print("Cluster Disk Usage:")
    print("-" * 80)
    df_response = client.get_df()
    if df_response["status"] == "success":
        df_data = df_response["data"]

        # Global stats
        stats = df_data["stats"]
        total = stats["total_bytes"]
        used = stats["total_used_bytes"]
        avail = stats["total_avail_bytes"]
        used_pct = (used / total * 100) if total > 0 else 0

        print(f"Global Statistics:")
        print(f"  - Total: {format_bytes(total)}")
        print(f"  - Used: {format_bytes(used)} ({used_pct:.2f}%)")
        print(f"  - Available: {format_bytes(avail)}")
        print()

        # Pool stats
        pools = df_data["pools"]
        print(f"Pool Statistics ({len(pools)} pools):")
        print()
        for pool in pools:
            pool_stats = pool["stats"]
            print(f"  {pool['name']} (ID: {pool['id']}):")
            print(f"    - Stored: {format_bytes(pool_stats['stored'])}")
            print(f"    - Objects: {pool_stats['objects']:,}")
            print(f"    - Used: {format_bytes(pool_stats['bytes_used'])}")
            print(f"    - Percent Used: {pool_stats['percent_used']:.4f}%")
            print()
    else:
        print(f"Error: {df_response.get('message', 'Unknown error')}")

    print("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        sys.exit(130)
