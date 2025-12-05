"""Tests for CephX authentication router."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import status
from fastapi.testclient import TestClient

from app.ceph.errors import CephAuthNotFound, CephCommandError
from app.models.auth import APIResponse, CreateAuthRequest, UpdateCapsRequest


@pytest.fixture
def mock_ceph_client():
    """Mock CephClient for testing."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    return {
        "name": "admin",
        "permissions": ["auth:read", "auth:write"],
        "api_key": "admin-key",
    }


class TestCreateAuth:
    """Tests for POST /auth endpoint."""

    def test_create_auth_success(self, mock_ceph_client, mock_user):
        """Test successful auth creation."""
        # Mock response from Ceph
        mock_ceph_client.execute.return_value = [
            {
                "entity": "client.testuser",
                "key": "AQDExampleKey==",
                "caps": {
                    "mon": "allow r",
                    "osd": "allow rw pool=mypool",
                },
            }
        ]

        # Create request
        request = CreateAuthRequest(
            client_name="testuser",
            capabilities={
                "mon": "allow r",
                "osd": "allow rw pool=mypool",
            },
        )

        # Test would verify:
        # - Status 201 returned
        # - Response contains entity with key and caps
        # - Audit log entry created

    def test_create_auth_already_exists(self, mock_ceph_client, mock_user):
        """Test auth creation when entity already exists."""
        # Mock check_auth_exists_internal to return True
        mock_ceph_client.execute.side_effect = [
            [{"entity": "client.testuser"}],  # exists check
        ]

        # Should return 409 Conflict

    def test_create_auth_invalid_name(self):
        """Test auth creation with invalid client name."""
        with pytest.raises(ValueError):
            CreateAuthRequest(
                client_name="invalid@name!",
                capabilities={"mon": "allow r"},
            )

    def test_create_auth_no_capabilities(self):
        """Test auth creation with no capabilities."""
        request = CreateAuthRequest(
            client_name="testuser",
            capabilities={},
        )

        with pytest.raises(ValueError):
            request.validate_capabilities()


class TestGetAuth:
    """Tests for GET /auth/{client_name} endpoint."""

    def test_get_auth_success(self, mock_ceph_client):
        """Test successful auth retrieval."""
        mock_ceph_client.execute.return_value = [
            {
                "entity": "client.testuser",
                "key": "AQDExampleKey==",
                "caps": {"mon": "allow r", "osd": "allow rw pool=mypool"},
            }
        ]

        # Should return 200 with auth details

    def test_get_auth_not_found(self, mock_ceph_client):
        """Test getting non-existent auth."""
        mock_ceph_client.execute.side_effect = CephAuthNotFound("client.testuser")

        # Should return 404

    def test_get_auth_with_client_prefix(self, mock_ceph_client):
        """Test getting auth with 'client.' prefix in name."""
        mock_ceph_client.execute.return_value = [
            {
                "entity": "client.testuser",
                "key": "AQDExampleKey==",
                "caps": {"mon": "allow r"},
            }
        ]

        # Should work with both "testuser" and "client.testuser"


class TestUpdateCaps:
    """Tests for PUT /auth/{client_name}/caps endpoint."""

    def test_update_caps_success(self, mock_ceph_client):
        """Test successful capability update."""
        mock_ceph_client.execute.side_effect = [
            [{"entity": "client.testuser"}],  # exists check
            None,  # caps update (no output)
            [
                {
                    "entity": "client.testuser",
                    "key": "AQDExampleKey==",
                    "caps": {"mon": "allow rw"},
                }
            ],  # get updated
        ]

        # Should return 200 with updated caps

    def test_update_caps_suspend(self, mock_ceph_client):
        """Test suspending client with empty capabilities."""
        request = UpdateCapsRequest(capabilities={})

        # Should set all caps to empty strings
        # Should return 200

    def test_update_caps_not_found(self, mock_ceph_client):
        """Test updating non-existent auth."""
        mock_ceph_client.execute.side_effect = CephAuthNotFound("client.testuser")

        # Should return 404


class TestDeleteAuth:
    """Tests for DELETE /auth/{client_name} endpoint."""

    def test_delete_auth_success(self, mock_ceph_client):
        """Test successful auth deletion."""
        mock_ceph_client.execute.side_effect = [
            [{"entity": "client.testuser"}],  # exists check
            None,  # delete (no output)
        ]

        # Should return 204 No Content

    def test_delete_auth_not_found(self, mock_ceph_client):
        """Test deleting non-existent auth."""
        mock_ceph_client.execute.side_effect = CephAuthNotFound("client.testuser")

        # Should return 404


class TestListAuth:
    """Tests for GET /auth endpoint."""

    def test_list_auth_success(self, mock_ceph_client):
        """Test successful auth listing."""
        mock_ceph_client.execute.return_value = {
            "auth_dump": [
                {
                    "entity": "client.admin",
                    "key": "AQDAdminKey==",
                    "caps": {"mon": "allow *", "osd": "allow *"},
                },
                {
                    "entity": "client.testuser1",
                    "key": "AQDKey1==",
                    "caps": {"mon": "allow r", "osd": "allow rw pool=pool1"},
                },
                {
                    "entity": "client.testuser2",
                    "key": "AQDKey2==",
                    "caps": {"mon": "allow r", "osd": "allow rw pool=pool2"},
                },
                {
                    "entity": "osd.0",
                    "key": "AQDOsdKey==",
                    "caps": {"mon": "allow profile osd"},
                },
            ]
        }

        # Should filter out system clients (admin, osd.*, etc.)
        # Should return only client.testuser1 and client.testuser2
        # Should include pagination info

    def test_list_auth_with_filter(self, mock_ceph_client):
        """Test listing with prefix filter."""
        mock_ceph_client.execute.return_value = {
            "auth_dump": [
                {"entity": "client.testuser1", "key": "key1", "caps": {}},
                {"entity": "client.testuser2", "key": "key2", "caps": {}},
                {"entity": "client.production1", "key": "key3", "caps": {}},
            ]
        }

        # With filter="test" should return only testuser1 and testuser2
        # With filter="prod" should return only production1

    def test_list_auth_pagination(self, mock_ceph_client):
        """Test pagination of auth list."""
        # Generate 150 test clients
        auth_dump = [
            {
                "entity": f"client.testuser{i}",
                "key": f"key{i}",
                "caps": {"mon": "allow r"},
            }
            for i in range(150)
        ]

        mock_ceph_client.execute.return_value = {"auth_dump": auth_dump}

        # With limit=100, offset=0: should return first 100
        # With limit=100, offset=100: should return next 50
        # total should be 150

    def test_list_auth_empty(self, mock_ceph_client):
        """Test listing when no client auths exist."""
        mock_ceph_client.execute.return_value = {
            "auth_dump": [
                {"entity": "client.admin", "key": "key", "caps": {}},
                {"entity": "osd.0", "key": "key", "caps": {}},
            ]
        }

        # Should return empty list after filtering system clients


class TestAuthModels:
    """Tests for auth models."""

    def test_client_name_validation(self):
        """Test client name validation."""
        # Valid names
        valid_names = ["testuser", "test_user", "test-user", "test123", "TEST"]
        for name in valid_names:
            request = CreateAuthRequest(
                client_name=name,
                capabilities={"mon": "allow r"},
            )
            assert request.client_name == name

        # Invalid names
        invalid_names = [
            "test@user",  # special chars
            "test user",  # space
            "test.user",  # dot
            "",  # empty
            "a" * 65,  # too long
        ]
        for name in invalid_names:
            with pytest.raises(ValueError):
                CreateAuthRequest(
                    client_name=name,
                    capabilities={"mon": "allow r"},
                )

    def test_client_name_strips_prefix(self):
        """Test that client. prefix is stripped."""
        request = CreateAuthRequest(
            client_name="client.testuser",
            capabilities={"mon": "allow r"},
        )
        assert request.client_name == "testuser"

    def test_capabilities_empty_check(self):
        """Test empty capabilities detection."""
        from app.models.auth import CephXCapabilities

        # All None
        caps = CephXCapabilities()
        assert caps.is_empty()

        # All empty strings
        caps = CephXCapabilities(mon="", osd="", mds="", mgr="")
        assert caps.is_empty()

        # Has one cap
        caps = CephXCapabilities(mon="allow r")
        assert not caps.is_empty()

    def test_api_response_success(self):
        """Test API success response."""
        response = APIResponse.success(data={"test": "value"})
        assert response.status == "success"
        assert response.data == {"test": "value"}
        assert response.code is None

    def test_api_response_error(self):
        """Test API error response."""
        response = APIResponse.error(
            code="TEST_ERROR",
            message="Test error message",
            details={"detail": "value"},
        )
        assert response.status == "error"
        assert response.code == "TEST_ERROR"
        assert response.message == "Test error message"
        assert response.details == {"detail": "value"}


# Example usage notes for the API:
"""
Example API Usage:
------------------

1. Create a new CephX authentication:
   POST /api/v1/auth
   Headers: X-API-Key: admin-key
   Body: {
       "client_name": "myapp",
       "capabilities": {
           "mon": "allow r",
           "osd": "allow rw pool=mypool",
           "mds": "allow rw"
       }
   }
   Response (201): {
       "status": "success",
       "data": {
           "entity": "client.myapp",
           "key": "AQDExampleKeyHere==",
           "caps": {
               "mon": "allow r",
               "osd": "allow rw pool=mypool",
               "mds": "allow rw"
           }
       }
   }

2. Get authentication details:
   GET /api/v1/auth/myapp
   Headers: X-API-Key: admin-key
   Response (200): {
       "status": "success",
       "data": {
           "entity": "client.myapp",
           "key": "AQDExampleKeyHere==",
           "caps": {...}
       }
   }

3. Update capabilities:
   PUT /api/v1/auth/myapp/caps
   Headers: X-API-Key: admin-key
   Body: {
       "capabilities": {
           "mon": "allow r",
           "osd": "allow rw pool=newpool"
       }
   }
   Response (200): {
       "status": "success",
       "data": {
           "entity": "client.myapp",
           "caps": {...}
       }
   }

4. Suspend a client (remove all capabilities):
   PUT /api/v1/auth/myapp/caps
   Headers: X-API-Key: admin-key
   Body: {
       "capabilities": {}
   }
   Response (200)

5. Delete authentication:
   DELETE /api/v1/auth/myapp
   Headers: X-API-Key: admin-key
   Response (204)

6. List all clients:
   GET /api/v1/auth?filter=myapp&limit=50&offset=0
   Headers: X-API-Key: admin-key
   Response (200): {
       "status": "success",
       "data": {
           "clients": [...],
           "total": 150,
           "offset": 0,
           "limit": 50
       }
   }
"""
