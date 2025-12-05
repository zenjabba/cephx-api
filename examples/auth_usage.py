#!/usr/bin/env python3
"""Example usage of CephX Authentication API."""

import asyncio
import sys
from typing import Any

import requests


class CephAuthClient:
    """Client for CephX Authentication API."""

    def __init__(self, base_url: str, api_key: str) -> None:
        """Initialize client.

        Args:
            base_url: Base URL of the API (e.g., http://localhost:8000/api/v1)
            api_key: API key for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

    def create_auth(
        self,
        client_name: str,
        capabilities: dict[str, str],
    ) -> dict[str, Any]:
        """Create a new CephX authentication.

        Args:
            client_name: Client name
            capabilities: Capabilities dictionary

        Returns:
            Created auth entity with key

        Raises:
            requests.HTTPError: If request fails
        """
        response = requests.post(
            f"{self.base_url}/auth",
            headers=self.headers,
            json={
                "client_name": client_name,
                "capabilities": capabilities,
            },
        )
        response.raise_for_status()
        return response.json()["data"]

    def get_auth(self, client_name: str) -> dict[str, Any]:
        """Get authentication details.

        Args:
            client_name: Client name

        Returns:
            Auth entity details

        Raises:
            requests.HTTPError: If request fails
        """
        response = requests.get(
            f"{self.base_url}/auth/{client_name}",
            headers=self.headers,
        )
        response.raise_for_status()
        return response.json()["data"]

    def update_caps(
        self,
        client_name: str,
        capabilities: dict[str, str],
    ) -> dict[str, Any]:
        """Update client capabilities.

        Args:
            client_name: Client name
            capabilities: New capabilities (empty dict to suspend)

        Returns:
            Updated auth entity

        Raises:
            requests.HTTPError: If request fails
        """
        response = requests.put(
            f"{self.base_url}/auth/{client_name}/caps",
            headers=self.headers,
            json={"capabilities": capabilities},
        )
        response.raise_for_status()
        return response.json()["data"]

    def delete_auth(self, client_name: str) -> None:
        """Delete authentication entity.

        Args:
            client_name: Client name

        Raises:
            requests.HTTPError: If request fails
        """
        response = requests.delete(
            f"{self.base_url}/auth/{client_name}",
            headers=self.headers,
        )
        response.raise_for_status()

    def list_auth(
        self,
        filter_prefix: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List authentication entities.

        Args:
            filter_prefix: Optional prefix filter
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of auth entities with pagination info

        Raises:
            requests.HTTPError: If request fails
        """
        params = {"limit": limit, "offset": offset}
        if filter_prefix:
            params["filter"] = filter_prefix

        response = requests.get(
            f"{self.base_url}/auth",
            headers=self.headers,
            params=params,
        )
        response.raise_for_status()
        return response.json()["data"]


def main() -> None:
    """Example usage of the CephX Authentication API."""
    # Initialize client
    client = CephAuthClient(
        base_url="http://localhost:8000/api/v1",
        api_key="admin-key",
    )

    print("=== CephX Authentication API Examples ===\n")

    # Example 1: Create a new authentication
    print("1. Creating new authentication for 'myapp'...")
    try:
        auth = client.create_auth(
            client_name="myapp",
            capabilities={
                "mon": "allow r",
                "osd": "allow rw pool=mypool",
                "mds": "allow rw path=/data",
            },
        )
        print(f"   Created: {auth['entity']}")
        print(f"   Key: {auth['key']}")
        print(f"   Capabilities: {auth['caps']}\n")
    except requests.HTTPError as e:
        if e.response.status_code == 409:
            print("   Already exists, continuing...\n")
        else:
            print(f"   Error: {e}\n")
            sys.exit(1)

    # Example 2: Get authentication details
    print("2. Getting authentication details...")
    try:
        auth = client.get_auth("myapp")
        print(f"   Entity: {auth['entity']}")
        print(f"   Key: {auth['key']}")
        print(f"   Capabilities: {auth['caps']}\n")
    except requests.HTTPError as e:
        print(f"   Error: {e}\n")

    # Example 3: Update capabilities
    print("3. Updating capabilities...")
    try:
        auth = client.update_caps(
            client_name="myapp",
            capabilities={
                "mon": "allow r",
                "osd": "allow rw pool=production",
            },
        )
        print(f"   Updated capabilities: {auth['caps']}\n")
    except requests.HTTPError as e:
        print(f"   Error: {e}\n")

    # Example 4: List all authentications
    print("4. Listing all client authentications...")
    try:
        result = client.list_auth(limit=10)
        print(f"   Total clients: {result['total']}")
        print(f"   Showing: {len(result['clients'])}")
        for auth in result["clients"][:5]:  # Show first 5
            print(f"   - {auth['entity']}")
        print()
    except requests.HTTPError as e:
        print(f"   Error: {e}\n")

    # Example 5: List with filter
    print("5. Listing clients with prefix 'my'...")
    try:
        result = client.list_auth(filter_prefix="my", limit=10)
        print(f"   Found: {result['total']} clients")
        for auth in result["clients"]:
            print(f"   - {auth['entity']}")
        print()
    except requests.HTTPError as e:
        print(f"   Error: {e}\n")

    # Example 6: Suspend a client (remove all capabilities)
    print("6. Suspending client 'myapp' (removing capabilities)...")
    try:
        auth = client.update_caps(
            client_name="myapp",
            capabilities={},
        )
        print(f"   Suspended. Capabilities: {auth['caps']}\n")
    except requests.HTTPError as e:
        print(f"   Error: {e}\n")

    # Example 7: Re-enable with new capabilities
    print("7. Re-enabling client with new capabilities...")
    try:
        auth = client.update_caps(
            client_name="myapp",
            capabilities={
                "mon": "allow r",
                "osd": "allow rw pool=mypool",
            },
        )
        print(f"   Re-enabled. Capabilities: {auth['caps']}\n")
    except requests.HTTPError as e:
        print(f"   Error: {e}\n")

    # Example 8: Delete authentication
    print("8. Deleting authentication 'myapp'...")
    try:
        client.delete_auth("myapp")
        print("   Deleted successfully\n")
    except requests.HTTPError as e:
        print(f"   Error: {e}\n")

    # Example 9: Verify deletion
    print("9. Verifying deletion...")
    try:
        client.get_auth("myapp")
        print("   ERROR: Still exists!\n")
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            print("   Confirmed: Authentication no longer exists\n")
        else:
            print(f"   Unexpected error: {e}\n")

    print("=== Examples completed ===")


if __name__ == "__main__":
    main()
