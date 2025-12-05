"""Ceph command execution client."""

import json
import logging
import subprocess
from typing import Any, Dict, List, Union

from app.core.config import get_settings
from app.core.exceptions import CephCommandFailedError

logger = logging.getLogger(__name__)


class CephClient:
    """Client for executing Ceph commands."""

    def __init__(self) -> None:
        """Initialize Ceph client with configuration."""
        self.settings = get_settings()
        self.timeout = self.settings.ceph_command_timeout

    def execute_command(
        self,
        command: List[str],
        parse_json: bool = False,
        check: bool = True,
    ) -> Union[Dict[str, Any], str]:
        """Execute a Ceph command and return the result.

        Args:
            command: Command to execute as list of arguments
            parse_json: Whether to parse JSON output
            check: Whether to raise exception on non-zero exit code

        Returns:
            Parsed JSON dict if parse_json=True, otherwise stdout string

        Raises:
            CephCommandFailedError: If command execution fails and check=True
        """
        full_command = ["ceph"] + command

        logger.info(f"Executing Ceph command: {' '.join(full_command)}")

        try:
            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )

            if check and result.returncode != 0:
                logger.error(
                    f"Command failed with exit code {result.returncode}: "
                    f"{result.stderr}"
                )
                raise CephCommandFailedError(
                    command=" ".join(full_command),
                    exit_code=result.returncode,
                    stderr=result.stderr.strip(),
                )

            stdout = result.stdout.strip()

            if parse_json:
                try:
                    return json.loads(stdout) if stdout else {}
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON output: {stdout}")
                    raise CephCommandFailedError(
                        command=" ".join(full_command),
                        exit_code=1,
                        stderr=f"Invalid JSON output: {e}",
                    )

            return stdout

        except subprocess.TimeoutExpired as e:
            logger.error(f"Command timed out after {self.timeout} seconds")
            raise CephCommandFailedError(
                command=" ".join(full_command),
                exit_code=-1,
                stderr=f"Command timed out after {self.timeout} seconds",
            ) from e

    def pool_exists(self, pool_name: str) -> bool:
        """Check if a pool exists.

        Args:
            pool_name: Name of the pool to check

        Returns:
            True if pool exists, False otherwise
        """
        try:
            pools = self.execute_command(
                ["osd", "pool", "ls", "--format", "json"],
                parse_json=True,
            )
            return pool_name in pools
        except CephCommandFailedError:
            return False

    def crush_rule_exists(self, rule_name: str) -> bool:
        """Check if a CRUSH rule exists.

        Args:
            rule_name: Name of the CRUSH rule to check

        Returns:
            True if rule exists, False otherwise
        """
        try:
            rules = self.execute_command(
                ["osd", "crush", "rule", "ls"],
                parse_json=False,
            )
            return rule_name in rules.split("\n")
        except CephCommandFailedError:
            return False

    def filesystem_exists(self, name: str) -> bool:
        """Check if a filesystem exists.

        Args:
            name: Name of the filesystem to check

        Returns:
            True if filesystem exists, False otherwise
        """
        try:
            filesystems = self.execute_command(
                ["fs", "ls", "--format", "json"],
                parse_json=True,
            )
            return any(fs.get("name") == name for fs in filesystems)
        except CephCommandFailedError:
            return False

    def create_pool(
        self,
        pool_name: str,
        pg_num: int,
        pool_type: str,
        crush_rule: str,
    ) -> None:
        """Create a Ceph pool.

        Args:
            pool_name: Name for the new pool
            pg_num: Number of placement groups
            pool_type: Pool type (replicated or erasure)
            crush_rule: CRUSH rule to use

        Raises:
            CephCommandFailedError: If pool creation fails
        """
        self.execute_command([
            "osd",
            "pool",
            "create",
            pool_name,
            str(pg_num),
            pool_type,
            crush_rule,
        ])

    def delete_pool(self, pool_name: str) -> None:
        """Delete a Ceph pool.

        Args:
            pool_name: Name of the pool to delete

        Raises:
            CephCommandFailedError: If pool deletion fails
        """
        self.execute_command([
            "osd",
            "pool",
            "delete",
            pool_name,
            pool_name,
            "--yes-i-really-really-mean-it",
        ])

    def create_filesystem(
        self,
        name: str,
        meta_pool: str,
        data_pool: str,
    ) -> None:
        """Create a CephFS filesystem.

        Args:
            name: Name for the new filesystem
            meta_pool: Metadata pool name
            data_pool: Data pool name

        Raises:
            CephCommandFailedError: If filesystem creation fails
        """
        self.execute_command([
            "fs",
            "new",
            name,
            meta_pool,
            data_pool,
        ])

    def set_filesystem_flag(
        self,
        name: str,
        flag: str,
        value: bool,
    ) -> None:
        """Set a filesystem flag.

        Args:
            name: Filesystem name
            flag: Flag name
            value: Flag value

        Raises:
            CephCommandFailedError: If command fails
        """
        self.execute_command([
            "fs",
            "set",
            name,
            flag,
            "true" if value else "false",
        ])

    def authorize_filesystem_client(
        self,
        filesystem: str,
        client_name: str,
        path: str,
        permissions: str,
    ) -> str:
        """Authorize a client for filesystem access.

        Args:
            filesystem: Filesystem name
            client_name: Client name (without 'client.' prefix)
            path: Path to authorize
            permissions: Permissions string (e.g., 'rw')

        Returns:
            The client auth key

        Raises:
            CephCommandFailedError: If authorization fails
        """
        output = self.execute_command([
            "fs",
            "authorize",
            filesystem,
            f"client.{client_name}",
            path,
            permissions,
        ])

        # Parse the key from output
        # Format: [client.name]\n\tkey = <key_value>
        for line in str(output).split("\n"):
            if "key" in line and "=" in line:
                return line.split("=", 1)[1].strip()

        raise CephCommandFailedError(
            command=f"fs authorize {filesystem}",
            exit_code=1,
            stderr="Failed to extract auth key from output",
        )

    def delete_auth_client(self, client_name: str) -> None:
        """Delete an authentication client.

        Args:
            client_name: Client name (without 'client.' prefix)

        Raises:
            CephCommandFailedError: If deletion fails
        """
        self.execute_command([
            "auth",
            "del",
            f"client.{client_name}",
        ], check=False)  # Don't fail if client doesn't exist

    def get_filesystem_info(self, name: str) -> Dict[str, Any]:
        """Get filesystem information.

        Args:
            name: Filesystem name

        Returns:
            Filesystem information dict

        Raises:
            CephCommandFailedError: If command fails
            FilesystemNotFoundError: If filesystem not found
        """
        from app.core.exceptions import FilesystemNotFoundError

        try:
            return self.execute_command(
                ["fs", "volume", "info", name, "--format", "json"],
                parse_json=True,
            )
        except CephCommandFailedError as e:
            if "not found" in e.details.get("stderr", "").lower():
                raise FilesystemNotFoundError(name) from e
            raise

    def list_filesystems(self) -> List[Dict[str, Any]]:
        """List all filesystems.

        Returns:
            List of filesystem information dicts

        Raises:
            CephCommandFailedError: If command fails
        """
        result = self.execute_command(
            ["fs", "ls", "--format", "json"],
            parse_json=True,
        )
        return result if isinstance(result, list) else []

    def get_cluster_df(self) -> Dict[str, Any]:
        """Get cluster data usage statistics.

        Returns:
            Cluster df information including pool stats

        Raises:
            CephCommandFailedError: If command fails
        """
        return self.execute_command(
            ["df", "detail", "--format", "json"],
            parse_json=True,
        )

    def remove_filesystem(self, name: str) -> None:
        """Remove a filesystem.

        Args:
            name: Filesystem name

        Raises:
            CephCommandFailedError: If removal fails
        """
        self.execute_command([
            "fs",
            "volume",
            "rm",
            name,
            "--yes-i-really-mean-it",
        ])


# Global client instance
ceph_client = CephClient()
