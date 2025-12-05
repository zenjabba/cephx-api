"""Tests for filesystem endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import FilesystemNotFoundError
from app.main import app

client = TestClient(app)


class TestFilesystemEndpoints:
    """Test suite for filesystem endpoints."""

    def test_health_check(self) -> None:
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    @patch("app.services.ceph_client.ceph_client")
    def test_create_filesystem_success(self, mock_client: MagicMock) -> None:
        """Test successful filesystem creation."""
        # Setup mocks
        mock_client.filesystem_exists.return_value = False
        mock_client.crush_rule_exists.return_value = True
        mock_client.pool_exists.return_value = False
        mock_client.authorize_filesystem_client.return_value = "AQBkey123=="

        response = client.post(
            "/api/v1/fs/fs",
            json={
                "name": "testfs",
                "crush_rule": "replicated_mach2",
                "meta_pool_pg": 16,
            },
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["name"] == "testfs"
        assert data["data"]["auth_created"] is True

    @patch("app.services.ceph_client.ceph_client")
    def test_create_filesystem_already_exists(self, mock_client: MagicMock) -> None:
        """Test filesystem creation when it already exists."""
        mock_client.filesystem_exists.return_value = True

        response = client.post(
            "/api/v1/fs/fs",
            json={"name": "testfs"},
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 409
        data = response.json()
        assert data["status"] == "error"
        assert data["code"] == "FS_ALREADY_EXISTS"

    @patch("app.services.ceph_client.ceph_client")
    def test_get_filesystem(self, mock_client: MagicMock) -> None:
        """Test getting filesystem info."""
        mock_client.get_filesystem_info.return_value = {"name": "testfs"}
        mock_client.list_filesystems.return_value = [
            {
                "name": "testfs",
                "metadata_pool": "cephfs.testfs.meta",
                "data_pools": ["cephfs.testfs.data"],
                "mds_count": 1,
            }
        ]

        response = client.get(
            "/api/v1/fs/fs/testfs",
            headers={"X-API-Key": "readonly-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["name"] == "testfs"

    @patch("app.services.ceph_client.ceph_client")
    def test_get_filesystem_not_found(self, mock_client: MagicMock) -> None:
        """Test getting non-existent filesystem."""
        mock_client.get_filesystem_info.side_effect = FilesystemNotFoundError("testfs")

        response = client.get(
            "/api/v1/fs/fs/testfs",
            headers={"X-API-Key": "readonly-key"},
        )

        assert response.status_code == 404
        data = response.json()
        assert data["status"] == "error"
        assert data["code"] == "FS_NOT_FOUND"

    @patch("app.services.ceph_client.ceph_client")
    def test_list_filesystems(self, mock_client: MagicMock) -> None:
        """Test listing filesystems."""
        mock_client.list_filesystems.return_value = [
            {
                "name": "testfs1",
                "metadata_pool": "cephfs.testfs1.meta",
                "data_pools": ["cephfs.testfs1.data"],
                "mds_count": 1,
            },
            {
                "name": "testfs2",
                "metadata_pool": "cephfs.testfs2.meta",
                "data_pools": ["cephfs.testfs2.data"],
                "mds_count": 1,
            },
        ]

        response = client.get(
            "/api/v1/fs/fs",
            headers={"X-API-Key": "readonly-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["count"] == 2
        assert len(data["data"]["filesystems"]) == 2

    @patch("app.services.ceph_client.ceph_client")
    def test_delete_filesystem_success(self, mock_client: MagicMock) -> None:
        """Test successful filesystem deletion."""
        mock_client.filesystem_exists.return_value = True

        response = client.delete(
            "/api/v1/fs/fs/testfs?confirm=testfs",
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 204

    @patch("app.services.ceph_client.ceph_client")
    def test_delete_filesystem_confirmation_required(
        self, mock_client: MagicMock
    ) -> None:
        """Test filesystem deletion without proper confirmation."""
        response = client.delete(
            "/api/v1/fs/fs/testfs?confirm=wrong",
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 400
        data = response.json()
        assert data["status"] == "error"
        assert data["code"] == "CONFIRMATION_REQUIRED"

    def test_unauthorized_access(self) -> None:
        """Test unauthorized access without API key."""
        response = client.get("/api/v1/fs/fs")

        assert response.status_code == 401
        data = response.json()
        assert data["status"] == "error"
        assert data["code"] == "INVALID_API_KEY"

    def test_insufficient_permissions(self) -> None:
        """Test access with insufficient permissions."""
        response = client.post(
            "/api/v1/fs/fs",
            json={"name": "testfs"},
            headers={"X-API-Key": "readonly-key"},
        )

        assert response.status_code == 403
        data = response.json()
        assert data["status"] == "error"
        assert data["code"] == "PERMISSION_DENIED"
