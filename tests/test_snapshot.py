"""Unit tests for snapshot schedule endpoints."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.ceph import CephFsNotFound, CephScheduleNotFound
from app.models.snapshot import AddSnapshotScheduleRequest


class TestSnapshotScheduleEndpoints:
    """Test cases for snapshot schedule management."""

    @pytest.fixture
    def mock_ceph_client(self):
        """Mock CephClient for testing."""
        with patch("app.routers.snapshot.CephClient") as mock:
            instance = mock.return_value
            instance.execute = AsyncMock()
            instance.fs_exists = AsyncMock(return_value=True)
            yield instance

    @pytest.mark.asyncio
    async def test_add_snapshot_schedule_success(self, mock_ceph_client):
        """Test successful snapshot schedule creation."""
        # Arrange
        mock_ceph_client.execute.return_value = ""

        # Import here to avoid circular imports
        from app.routers.snapshot import add_snapshot_schedule

        request = AddSnapshotScheduleRequest(
            path="/data",
            schedule="1d",
            start_time="02:00:00",
            retention={"daily": 7, "weekly": 4},
        )

        # Act
        response = await add_snapshot_schedule("cephfs", request)

        # Assert
        assert response.status_code == status.HTTP_201_CREATED
        body = json.loads(response.body)
        assert body["status"] == "success"
        assert body["data"]["schedule"] == "1d"
        assert body["data"]["path"] == "/data"

        # Verify commands executed
        calls = mock_ceph_client.execute.call_args_list
        assert len(calls) == 3  # 1 add + 2 retention policies

        # Check main schedule command
        assert calls[0][0][0] == ["fs", "snap-schedule", "add", "/data", "1d", "02:00:00", "--fs", "cephfs"]

    @pytest.mark.asyncio
    async def test_add_schedule_filesystem_not_found(self, mock_ceph_client):
        """Test schedule creation with non-existent filesystem."""
        # Arrange
        mock_ceph_client.fs_exists.return_value = False

        from app.routers.snapshot import add_snapshot_schedule

        request = AddSnapshotScheduleRequest(path="/", schedule="1d")

        # Act
        response = await add_snapshot_schedule("nonexistent", request)

        # Assert
        assert response.status_code == status.HTTP_404_NOT_FOUND
        body = json.loads(response.body)
        assert body["status"] == "error"
        assert body["code"] == "CEPH_FS_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_get_snapshot_schedules_success(self, mock_ceph_client):
        """Test retrieving snapshot schedules."""
        # Arrange
        mock_ceph_client.execute.return_value = [
            {
                "path": "/",
                "schedule": "1d",
                "retention": {"d": 7, "w": 4},
                "start": "00:00:00",
                "subvol": None,
            }
        ]

        from app.routers.snapshot import get_snapshot_schedules

        # Act
        response = await get_snapshot_schedules("cephfs", "/")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        body = json.loads(response.body)
        assert body["status"] == "success"
        assert body["data"]["count"] == 1
        assert body["data"]["schedules"][0]["schedule"] == "1d"

    @pytest.mark.asyncio
    async def test_get_schedules_empty(self, mock_ceph_client):
        """Test retrieving schedules when none exist."""
        # Arrange
        mock_ceph_client.execute.return_value = []

        from app.routers.snapshot import get_snapshot_schedules

        # Act
        response = await get_snapshot_schedules("cephfs", "/")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        body = json.loads(response.body)
        assert body["status"] == "success"
        assert body["data"]["count"] == 0
        assert body["data"]["schedules"] == []

    @pytest.mark.asyncio
    async def test_remove_snapshot_schedule_success(self, mock_ceph_client):
        """Test successful schedule removal."""
        # Arrange
        mock_ceph_client.execute.return_value = ""

        from app.routers.snapshot import remove_snapshot_schedule

        # Act
        response = await remove_snapshot_schedule("cephfs", "/", "1d")

        # Assert
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify command
        calls = mock_ceph_client.execute.call_args_list
        assert calls[0][0][0] == ["fs", "snap-schedule", "remove", "/", "1d", "--fs", "cephfs"]

    @pytest.mark.asyncio
    async def test_remove_all_schedules(self, mock_ceph_client):
        """Test removing all schedules on a path."""
        # Arrange
        mock_ceph_client.execute.return_value = ""

        from app.routers.snapshot import remove_snapshot_schedule

        # Act
        response = await remove_snapshot_schedule("cephfs", "/data", None)

        # Assert
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify command (no schedule parameter)
        calls = mock_ceph_client.execute.call_args_list
        assert calls[0][0][0] == ["fs", "snap-schedule", "remove", "/data", "--fs", "cephfs"]

    @pytest.mark.asyncio
    async def test_list_snapshots_not_implemented(self):
        """Test that snapshot listing returns 501."""
        from app.routers.snapshot import list_snapshots

        # Act
        response = await list_snapshots("cephfs", "/", 100, False)

        # Assert
        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
        body = json.loads(response.body)
        assert body["status"] == "error"
        assert body["code"] == "NOT_IMPLEMENTED"


class TestScheduleValidation:
    """Test schedule format validation."""

    @pytest.mark.parametrize(
        "schedule,expected",
        [
            ("1h", True),
            ("6h", True),
            ("1d", True),
            ("2d", True),
            ("1w", True),
            ("1M", True),
            ("1y", True),
            ("24h", True),
            ("1x", False),  # Invalid unit
            ("h", False),  # Missing number
            ("0d", False),  # Zero
            ("-1d", False),  # Negative
            ("1", False),  # Missing unit
        ],
    )
    def test_schedule_format_validation(self, schedule: str, expected: bool):
        """Test schedule format validation."""
        from pydantic import ValidationError

        try:
            request = AddSnapshotScheduleRequest(schedule=schedule)
            assert expected, f"Expected {schedule} to fail validation"
            assert request.schedule == schedule
        except ValidationError:
            assert not expected, f"Expected {schedule} to pass validation"

    @pytest.mark.parametrize(
        "path,expected",
        [
            ("/", True),
            ("/data", True),
            ("/data/users", True),
            ("/data/users/john", True),
            ("data", False),  # Doesn't start with /
            ("/data/", False),  # Ends with /
            ("//data", False),  # Double slash
            ("/data//users", False),  # Double slash
            ("/data\x00users", False),  # Null byte
        ],
    )
    def test_path_validation(self, path: str, expected: bool):
        """Test path format validation."""
        from pydantic import ValidationError

        try:
            request = AddSnapshotScheduleRequest(path=path, schedule="1d")
            assert expected, f"Expected {path} to fail validation"
            assert request.path == path
        except ValidationError:
            assert not expected, f"Expected {path} to pass validation"


class TestRetentionMapping:
    """Test retention unit mapping."""

    def test_retention_unit_mapping(self):
        """Test mapping from API units to Ceph units."""
        from app.routers.snapshot import _map_retention_unit

        assert _map_retention_unit("hourly") == "h"
        assert _map_retention_unit("daily") == "d"
        assert _map_retention_unit("weekly") == "w"
        assert _map_retention_unit("monthly") == "m"
        assert _map_retention_unit("yearly") == "y"
        assert _map_retention_unit("h") == "h"  # Already mapped


class TestErrorHandling:
    """Test error handling and responses."""

    @pytest.mark.asyncio
    async def test_ceph_error_conversion(self):
        """Test CephCommandError to API response conversion."""
        from app.ceph import CephFsNotFound
        from app.routers.snapshot import _handle_ceph_error

        error = CephFsNotFound("test-fs")
        response = _handle_ceph_error(error)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        body = json.loads(response.body)
        assert body["status"] == "error"
        assert body["code"] == "CEPH_FS_NOT_FOUND"
        assert "test-fs" in body["message"]


# Fixture for FastAPI test client (if needed for integration tests)
@pytest.fixture
def client():
    """Create test client."""
    from fastapi import FastAPI
    from app.routers import snapshot

    app = FastAPI()
    app.include_router(snapshot.router, prefix="/api/v1")

    return TestClient(app)


# Example integration test using the client
def test_add_schedule_integration(client):
    """Integration test for adding schedule (requires mocking)."""
    # This would require full app setup and mocking
    # Shown as example structure
    pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
