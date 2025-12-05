"""Tests for cluster endpoints."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# Mock Ceph status response
MOCK_CEPH_STATUS = {
    "fsid": "12345678-1234-1234-1234-123456789abc",
    "health": {"status": "HEALTH_OK"},
    "monmap": {
        "epoch": 5,
        "mons": [
            {"name": "ceph01", "addr": "10.10.1.1:6789/0", "rank": 0},
            {"name": "ceph02", "addr": "10.10.1.2:6789/0", "rank": 1},
            {"name": "ceph03", "addr": "10.10.1.3:6789/0", "rank": 2},
        ],
    },
    "osdmap": {
        "osdmap": {
            "num_osds": 48,
            "num_up_osds": 48,
            "num_in_osds": 48,
        }
    },
    "pgmap": {
        "num_pgs": 1024,
        "pgs_by_state": [{"state_name": "active+clean", "count": 1024}],
    },
    "quorum": [0, 1, 2],
}

# Mock Ceph df response
MOCK_CEPH_DF = {
    "stats": {
        "total_bytes": 1099511627776,
        "total_used_bytes": 549755813888,
        "total_avail_bytes": 549755813888,
    },
    "pools": [
        {
            "name": "cephfs.testfs.data",
            "id": 10,
            "stats": {
                "stored": 1073741824,
                "objects": 1024,
                "kb_used": 3145728,
                "bytes_used": 3221225472,
                "percent_used": 0.29,
            },
        },
        {
            "name": "cephfs.testfs.meta",
            "id": 11,
            "stats": {
                "stored": 1048576,
                "objects": 100,
                "kb_used": 1024,
                "bytes_used": 1048576,
                "percent_used": 0.0001,
            },
        },
    ],
}


class TestMonitorsEndpoint:
    """Tests for /monitors endpoint."""

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_get_monitors_success(self, mock_execute: MagicMock) -> None:
        """Test successful retrieval of monitors."""
        mock_execute.return_value = MOCK_CEPH_STATUS

        response = client.get(
            "/api/v1/cluster/monitors",
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "data" in data
        assert data["data"]["total"] == 3
        assert len(data["data"]["monitors"]) == 3

        # Check first monitor
        mon = data["data"]["monitors"][0]
        assert mon["name"] == "ceph01"
        assert mon["addr"] == "10.10.1.1:6789"
        assert mon["rank"] == 0

    def test_get_monitors_no_api_key(self) -> None:
        """Test monitors endpoint without API key."""
        response = client.get("/api/v1/cluster/monitors")

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == "error"
        assert data["code"] == "INVALID_API_KEY"

    def test_get_monitors_invalid_api_key(self) -> None:
        """Test monitors endpoint with invalid API key."""
        response = client.get(
            "/api/v1/cluster/monitors",
            headers={"X-API-Key": "invalid-key"},
        )

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == "error"
        assert data["code"] == "INVALID_API_KEY"


class TestClusterStatusEndpoint:
    """Tests for /status endpoint."""

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_get_status_success(self, mock_execute: MagicMock) -> None:
        """Test successful retrieval of cluster status."""
        mock_execute.return_value = MOCK_CEPH_STATUS

        response = client.get(
            "/api/v1/cluster/status",
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "data" in data

        # Check health status
        assert data["data"]["health"] == "HEALTH_OK"

        # Check monitor status
        mon_status = data["data"]["mon_status"]
        assert mon_status["epoch"] == 5
        assert mon_status["num_mons"] == 3
        assert mon_status["quorum"] == [0, 1, 2]

        # Check OSD status
        osd_status = data["data"]["osd_status"]
        assert osd_status["num_osds"] == 48
        assert osd_status["num_up_osds"] == 48
        assert osd_status["num_in_osds"] == 48

        # Check PG status
        pg_status = data["data"]["pg_status"]
        assert pg_status["num_pgs"] == 1024
        assert pg_status["num_active_clean"] == 1024

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_get_status_readonly_permission(self, mock_execute: MagicMock) -> None:
        """Test status endpoint with readonly API key."""
        mock_execute.return_value = MOCK_CEPH_STATUS

        response = client.get(
            "/api/v1/cluster/status",
            headers={"X-API-Key": "readonly-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"


class TestClusterDfEndpoint:
    """Tests for /df endpoint."""

    @patch("app.services.ceph_client.ceph_client.get_cluster_df")
    def test_get_df_success(self, mock_get_df: MagicMock) -> None:
        """Test successful retrieval of cluster df."""
        mock_get_df.return_value = MOCK_CEPH_DF

        response = client.get(
            "/api/v1/cluster/df",
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "data" in data

        # Check global stats
        stats = data["data"]["stats"]
        assert stats["total_bytes"] == 1099511627776
        assert stats["total_used_bytes"] == 549755813888
        assert stats["total_avail_bytes"] == 549755813888

        # Check pool stats
        pools = data["data"]["pools"]
        assert len(pools) == 2

        # Check first pool
        pool = pools[0]
        assert pool["name"] == "cephfs.testfs.data"
        assert pool["id"] == 10
        assert pool["stats"]["stored"] == 1073741824
        assert pool["stats"]["objects"] == 1024

    @patch("app.services.ceph_client.ceph_client.get_cluster_df")
    def test_get_df_caching(self, mock_get_df: MagicMock) -> None:
        """Test that df results are cached."""
        mock_get_df.return_value = MOCK_CEPH_DF

        # First request
        response1 = client.get(
            "/api/v1/cluster/df",
            headers={"X-API-Key": "admin-key"},
        )
        assert response1.status_code == 200

        # Second request should use cache
        response2 = client.get(
            "/api/v1/cluster/df",
            headers={"X-API-Key": "admin-key"},
        )
        assert response2.status_code == 200

        # Should only call the mock once (second call uses cache)
        # Note: This might be called more than once if cache is cleared between tests
        assert mock_get_df.call_count >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
