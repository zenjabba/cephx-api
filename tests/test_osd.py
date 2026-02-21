"""Tests for OSD endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

# Mock ceph osd dump response (trimmed to relevant fields)
MOCK_OSD_DUMP = {
    "osds": [
        {"osd": 0, "up": 1, "in": 1, "weight": 1.0},
        {"osd": 1, "up": 1, "in": 1, "weight": 1.0},
        {"osd": 285, "up": 1, "in": 0, "weight": 0.0},
        {"osd": 286, "up": 0, "in": 0, "weight": 0.0},
    ],
}


class TestOSDStatusEndpoint:
    """Tests for GET /ceph/osd/{osd_id}/status."""

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_get_osd_status_up_in(self, mock_execute: MagicMock) -> None:
        """Test getting status of an OSD that is up and in."""
        mock_execute.return_value = MOCK_OSD_DUMP

        response = client.get(
            "/api/v1/ceph/osd/0/status",
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["osd"] == 0
        assert data["data"]["up"] == 1
        assert data["data"]["in"] == 1

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_get_osd_status_up_out(self, mock_execute: MagicMock) -> None:
        """Test getting status of an OSD that is up but out."""
        mock_execute.return_value = MOCK_OSD_DUMP

        response = client.get(
            "/api/v1/ceph/osd/285/status",
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["osd"] == 285
        assert data["data"]["up"] == 1
        assert data["data"]["in"] == 0

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_get_osd_status_down_out(self, mock_execute: MagicMock) -> None:
        """Test getting status of an OSD that is down and out."""
        mock_execute.return_value = MOCK_OSD_DUMP

        response = client.get(
            "/api/v1/ceph/osd/286/status",
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["osd"] == 286
        assert data["data"]["up"] == 0
        assert data["data"]["in"] == 0

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_get_osd_status_not_found(self, mock_execute: MagicMock) -> None:
        """Test getting status of a non-existent OSD returns 404."""
        mock_execute.return_value = MOCK_OSD_DUMP

        response = client.get(
            "/api/v1/ceph/osd/9999/status",
            headers={"X-API-Key": "admin-key"},
        )

        assert response.status_code == 404
        data = response.json()
        assert data["status"] == "error"
        assert data["code"] == "OSD_NOT_FOUND"

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_get_osd_status_readonly_key(self, mock_execute: MagicMock) -> None:
        """Test OSD status with readonly key (has osd:read)."""
        mock_execute.return_value = MOCK_OSD_DUMP

        response = client.get(
            "/api/v1/ceph/osd/0/status",
            headers={"X-API-Key": "readonly-key"},
        )

        assert response.status_code == 200

    def test_get_osd_status_no_api_key(self) -> None:
        """Test OSD status without API key."""
        response = client.get("/api/v1/ceph/osd/0/status")

        assert response.status_code == 401
        data = response.json()
        assert data["code"] == "INVALID_API_KEY"


class TestOSDFlagEndpoint:
    """Tests for POST /ceph/osd/flags."""

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_set_noout(self, mock_execute: MagicMock) -> None:
        """Test setting noout flag."""
        mock_execute.return_value = "noout is set"

        response = client.post(
            "/api/v1/ceph/osd/flags",
            headers={"X-API-Key": "admin-key"},
            json={"flag": "noout", "action": "set"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["ok"] is True
        assert "noout" in data["data"]["message"]
        mock_execute.assert_called_once_with(["osd", "set", "noout"])

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_unset_noout(self, mock_execute: MagicMock) -> None:
        """Test unsetting noout flag."""
        mock_execute.return_value = "noout is unset"

        response = client.post(
            "/api/v1/ceph/osd/flags",
            headers={"X-API-Key": "admin-key"},
            json={"flag": "noout", "action": "unset"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["ok"] is True
        mock_execute.assert_called_once_with(["osd", "unset", "noout"])

    @patch("app.services.ceph_client.ceph_client.execute_command")
    def test_set_norebalance(self, mock_execute: MagicMock) -> None:
        """Test setting norebalance flag."""
        mock_execute.return_value = "norebalance is set"

        response = client.post(
            "/api/v1/ceph/osd/flags",
            headers={"X-API-Key": "admin-key"},
            json={"flag": "norebalance", "action": "set"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["ok"] is True
        mock_execute.assert_called_once_with(["osd", "set", "norebalance"])

    def test_invalid_flag_rejected(self) -> None:
        """Test that disallowed flags are rejected at validation."""
        response = client.post(
            "/api/v1/ceph/osd/flags",
            headers={"X-API-Key": "admin-key"},
            json={"flag": "noup", "action": "set"},
        )

        assert response.status_code == 422
        data = response.json()
        assert data["status"] == "error"
        assert data["code"] == "VALIDATION_ERROR"

    def test_invalid_action_rejected(self) -> None:
        """Test that invalid actions are rejected."""
        response = client.post(
            "/api/v1/ceph/osd/flags",
            headers={"X-API-Key": "admin-key"},
            json={"flag": "noout", "action": "toggle"},
        )

        assert response.status_code == 422

    def test_flag_requires_write_permission(self) -> None:
        """Test that readonly key cannot set flags."""
        response = client.post(
            "/api/v1/ceph/osd/flags",
            headers={"X-API-Key": "readonly-key"},
            json={"flag": "noout", "action": "set"},
        )

        assert response.status_code == 403
        data = response.json()
        assert data["code"] == "PERMISSION_DENIED"

    def test_flag_no_api_key(self) -> None:
        """Test flag endpoint without API key."""
        response = client.post(
            "/api/v1/ceph/osd/flags",
            json={"flag": "noout", "action": "set"},
        )

        assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
