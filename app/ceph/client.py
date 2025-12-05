"""Ceph command execution client."""

import asyncio
import json
import logging
import shlex
from typing import Any, Dict, List, Tuple, Union

from app.ceph.errors import (
    CephClusterUnavailable,
    CephCommandError,
    CephFsNotFound,
    CephTimeout,
)

logger = logging.getLogger(__name__)


class CephClient:
    """Client for executing Ceph commands."""

    def __init__(
        self,
        ceph_binary: str = "/usr/bin/ceph",
        timeout: int = 30,
        connection_timeout: int = 5,
    ) -> None:
        """Initialize CephClient.

        Args:
            ceph_binary: Path to the ceph binary
            timeout: Command execution timeout in seconds
            connection_timeout: Connection timeout in seconds
        """
        self.ceph_binary = ceph_binary
        self.timeout = timeout
        self.connection_timeout = connection_timeout

    async def execute(
        self,
        command: List[str],
        *,
        timeout: Union[int, None] = None,
        format_json: bool = False,
    ) -> Tuple[Dict[str, Any], str]:
        """Execute a Ceph command.

        Args:
            command: Command arguments (without 'ceph' prefix)
            timeout: Override default timeout
            format_json: Whether to add --format json and parse output

        Returns:
            Parsed JSON dict if format_json=True, otherwise raw stdout string

        Raises:
            CephClusterUnavailable: If cluster is unreachable
            CephCommandError: If command execution fails
            CephTimeout: If command times out
        """
        timeout_val = timeout or self.timeout
        cmd = [self.ceph_binary] + command

        if format_json and "--format" not in command:
            cmd.extend(["--format", "json"])

        logger.info(f"Executing Ceph command: {' '.join(shlex.quote(c) for c in cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_val,
            )

            stdout = stdout_bytes.decode("utf-8").strip()
            stderr = stderr_bytes.decode("utf-8").strip()

            logger.debug(f"Command stdout: {stdout}")
            if stderr:
                logger.debug(f"Command stderr: {stderr}")

            if process.returncode != 0:
                self._handle_error(process.returncode, stderr, stdout, command)

            if format_json:
                if not stdout:
                    return {}
                try:
                    return json.loads(stdout)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON output: {stdout}")
                    raise CephCommandError(
                        message="Failed to parse Ceph command output",
                        error_code="CEPH_JSON_PARSE_ERROR",
                        details={"output": stdout, "error": str(e)},
                    ) from e

            return stdout

        except asyncio.TimeoutError as e:
            logger.error(f"Command timed out after {timeout_val}s: {' '.join(cmd)}")
            raise CephTimeout(
                message=f"Command timed out after {timeout_val}s",
                details={"command": cmd, "timeout": timeout_val},
            ) from e
        except FileNotFoundError as e:
            logger.error(f"Ceph binary not found: {self.ceph_binary}")
            raise CephClusterUnavailable(
                message=f"Ceph binary not found: {self.ceph_binary}",
                details={"binary_path": self.ceph_binary},
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error executing command: {e}")
            raise CephCommandError(
                message=f"Unexpected error executing Ceph command: {str(e)}",
                details={"command": cmd, "error_type": type(e).__name__},
            ) from e

    def _handle_error(
        self,
        returncode: int,
        stderr: str,
        stdout: str,
        command: List[str],
    ) -> None:
        """Handle command execution errors.

        Args:
            returncode: Process return code
            stderr: Standard error output
            stdout: Standard output
            command: Command that was executed

        Raises:
            CephFsNotFound: If filesystem not found
            CephClusterUnavailable: If cluster is unavailable
            CephCommandError: For other errors
        """
        error_msg = stderr or stdout or f"Command failed with exit code {returncode}"

        # Check for specific error patterns
        error_lower = error_msg.lower()

        if "no such file or directory" in error_lower and "fs" in " ".join(command):
            # Try to extract filesystem name
            fs_name = None
            if "--fs" in command:
                try:
                    fs_idx = command.index("--fs")
                    if fs_idx + 1 < len(command):
                        fs_name = command[fs_idx + 1]
                except (ValueError, IndexError):
                    pass

            raise CephFsNotFound(fs_name or "unknown")

        if any(
            phrase in error_lower
            for phrase in ["cluster unavailable", "connection refused", "no such host"]
        ):
            raise CephClusterUnavailable(
                message="Cannot connect to Ceph cluster",
                details={"stderr": stderr, "stdout": stdout},
            )

        if "not found" in error_lower or "does not exist" in error_lower:
            raise CephCommandError(
                message=error_msg,
                error_code="CEPH_NOT_FOUND",
                status_code=404,
                details={"command": command, "stderr": stderr, "stdout": stdout},
            )

        if "already exists" in error_lower:
            raise CephCommandError(
                message=error_msg,
                error_code="CEPH_ALREADY_EXISTS",
                status_code=409,
                details={"command": command, "stderr": stderr, "stdout": stdout},
            )

        if "permission denied" in error_lower or "unauthorized" in error_lower:
            raise CephCommandError(
                message=error_msg,
                error_code="CEPH_PERMISSION_DENIED",
                status_code=403,
                details={"command": command, "stderr": stderr, "stdout": stdout},
            )

        # Generic error
        raise CephCommandError(
            message=error_msg,
            error_code="CEPH_COMMAND_FAILED",
            status_code=500,
            details={
                "command": command,
                "returncode": returncode,
                "stderr": stderr,
                "stdout": stdout,
            },
        )

    async def fs_exists(self, fs_name: str) -> bool:
        """Check if a filesystem exists.

        Args:
            fs_name: Filesystem name

        Returns:
            True if filesystem exists, False otherwise
        """
        try:
            result = await self.execute(["fs", "ls"], format_json=True)
            if isinstance(result, dict):
                filesystems = result.get("filesystems", [])
            else:
                filesystems = result if isinstance(result, list) else []

            return any(fs.get("name") == fs_name for fs in filesystems)
        except CephCommandError:
            return False
