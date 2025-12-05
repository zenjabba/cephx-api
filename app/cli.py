#!/usr/bin/env python3
"""
Ceph Management REST API - CLI Management Tool

This CLI tool provides management commands for API keys and audit logs.
"""

import argparse
import os
import secrets
import sqlite3
import string
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    import hashlib
    BCRYPT_AVAILABLE = False

try:
    from colorama import Fore, Style, init as colorama_init
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False

from tabulate import tabulate

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install pyyaml")
    sys.exit(1)


# Valid permissions
VALID_PERMISSIONS = {
    "auth:read",
    "auth:write",
    "fs:read",
    "fs:write",
    "snapshot:read",
    "snapshot:write",
    "cluster:read",
    "admin:*",
}


class Colors:
    """Color codes for terminal output."""

    def __init__(self):
        if COLORAMA_AVAILABLE and sys.stdout.isatty():
            colorama_init(autoreset=True)
            self.GREEN = Fore.GREEN
            self.RED = Fore.RED
            self.YELLOW = Fore.YELLOW
            self.BLUE = Fore.BLUE
            self.CYAN = Fore.CYAN
            self.MAGENTA = Fore.MAGENTA
            self.BOLD = Style.BRIGHT
            self.RESET = Style.RESET_ALL
        else:
            # No colors if not in terminal or colorama not available
            self.GREEN = ""
            self.RED = ""
            self.YELLOW = ""
            self.BLUE = ""
            self.CYAN = ""
            self.MAGENTA = ""
            self.BOLD = ""
            self.RESET = ""


colors = Colors()


class ConfigManager:
    """Manages configuration loading from YAML and environment variables."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self._find_config()
        self.config = self._load_config()

    def _find_config(self) -> str:
        """Find config.yaml in the project root."""
        # Try current directory first
        current = Path.cwd() / "config.yaml"
        if current.exists():
            return str(current)

        # Try script directory
        script_dir = Path(__file__).parent.parent / "config.yaml"
        if script_dir.exists():
            return str(script_dir)

        # Try common locations
        for path in ["/etc/cephx-api/config.yaml", "~/.cephx-api/config.yaml"]:
            expanded = Path(path).expanduser()
            if expanded.exists():
                return str(expanded)

        # Return default path even if it doesn't exist
        return str(Path(__file__).parent.parent / "config.yaml")

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        try:
            with open(self.config_path) as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            print(f"{colors.YELLOW}Warning: Config file not found at {self.config_path}{colors.RESET}")
            print("Using default configuration values.")
            return self._default_config()
        except yaml.YAMLError as e:
            print(f"{colors.RED}Error parsing config file: {e}{colors.RESET}")
            sys.exit(1)

    def _default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            "database": {"path": "/var/lib/cephx-api/api.db"},
            "security": {
                "default_rate_limit": 60,
                "max_rate_limit": 1000,
                "api_key_ttl_days": 365,
            },
        }

    def get_db_path(self) -> str:
        """Get database path with environment variable override."""
        return os.environ.get(
            "CEPHX_DB_PATH",
            self.config.get("database", {}).get("path", "/var/lib/cephx-api/api.db")
        )

    def get_default_rate_limit(self) -> int:
        """Get default rate limit."""
        return self.config.get("security", {}).get("default_rate_limit", 60)

    def get_max_rate_limit(self) -> int:
        """Get maximum rate limit."""
        return self.config.get("security", {}).get("max_rate_limit", 1000)


class DatabaseManager:
    """Manages SQLite database operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_db_directory()

    def _ensure_db_directory(self):
        """Ensure database directory exists."""
        db_dir = Path(self.db_path).parent
        try:
            db_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            print(f"{colors.RED}Error: Permission denied creating directory {db_dir}{colors.RESET}")
            print(f"Try running with sudo or set CEPHX_DB_PATH to a writable location.")
            sys.exit(1)

    def get_connection(self) -> sqlite3.Connection:
        """Get database connection."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            print(f"{colors.RED}Database error: {e}{colors.RESET}")
            sys.exit(1)

    def init_db(self):
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Create api_keys table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    key_hash TEXT NOT NULL,
                    permissions TEXT NOT NULL,
                    rate_limit INTEGER NOT NULL DEFAULT 60,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    created_by TEXT,
                    notes TEXT
                )
            """)

            # Create audit_log table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    api_key_prefix TEXT NOT NULL,
                    source_ip TEXT NOT NULL,
                    method TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    response_time_ms REAL NOT NULL,
                    user_agent TEXT,
                    request_size INTEGER,
                    response_size INTEGER,
                    error_message TEXT
                )
            """)

            # Create indexes
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_keys_name ON api_keys(name)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_api_keys_enabled ON api_keys(enabled)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_log_api_key ON audit_log(api_key_prefix)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_log_endpoint ON audit_log(endpoint)
            """)

            conn.commit()
            print(f"{colors.GREEN}Database initialized successfully at {self.db_path}{colors.RESET}")


class APIKeyManager:
    """Manages API key operations."""

    def __init__(self, db: DatabaseManager, config: ConfigManager):
        self.db = db
        self.config = config

    @staticmethod
    def hash_key(key: str) -> str:
        """Hash an API key for storage."""
        if BCRYPT_AVAILABLE:
            return bcrypt.hashpw(key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        else:
            # Fallback to SHA-256 (less secure but no dependencies)
            return hashlib.sha256(key.encode('utf-8')).hexdigest()

    @staticmethod
    def generate_api_key(name: str) -> str:
        """
        Generate a new API key with format: {env}_{client}_{random20chars}

        Args:
            name: Name/description for the key

        Returns:
            Generated API key string
        """
        # Extract environment from name
        name_lower = name.lower()
        if "prod" in name_lower or "production" in name_lower:
            env = "prod"
        elif "dev" in name_lower or "development" in name_lower:
            env = "dev"
        elif "test" in name_lower or "testing" in name_lower:
            env = "test"
        elif "admin" in name_lower or "administrator" in name_lower:
            env = "admin"
        else:
            env = "api"

        # Extract client name (simplified, alphanumeric only, max 10 chars)
        client = "".join(c for c in name_lower if c.isalnum() or c.isspace())
        client = client.replace(" ", "")[:10]
        if not client:
            client = "client"

        # Generate 20 random alphanumeric characters
        alphabet = string.ascii_lowercase + string.digits
        random_part = ''.join(secrets.choice(alphabet) for _ in range(20))

        return f"{env}_{client}_{random_part}"

    def create_api_key(
        self,
        name: str,
        permissions: List[str],
        rate_limit: int,
        expires: Optional[str] = None,
        created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> str:
        """
        Create a new API key.

        Args:
            name: Name/description for the key
            permissions: List of permissions
            rate_limit: Requests per minute
            expires: Expiration date in ISO format
            created_by: Who created the key
            notes: Additional notes

        Returns:
            Generated API key (plaintext, shown only once)
        """
        # Validate permissions
        invalid_perms = set(permissions) - VALID_PERMISSIONS
        if invalid_perms:
            raise ValueError(f"Invalid permissions: {', '.join(invalid_perms)}")

        # Validate rate limit
        max_limit = self.config.get_max_rate_limit()
        if rate_limit > max_limit:
            raise ValueError(f"Rate limit cannot exceed {max_limit}")

        # Generate API key
        api_key = self.generate_api_key(name)
        key_hash = self.hash_key(api_key)

        # Get current timestamp
        now = datetime.now(timezone.utc).isoformat()

        # Parse expiration if provided
        expires_at = None
        if expires:
            try:
                expires_dt = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                expires_at = expires_dt.isoformat()
            except ValueError:
                raise ValueError(f"Invalid expiration date format: {expires}")

        # Store in database
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO api_keys
                    (name, key_hash, permissions, rate_limit, enabled, expires_at, created_at, created_by, notes)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                """, (
                    name,
                    key_hash,
                    ','.join(permissions),
                    rate_limit,
                    expires_at,
                    now,
                    created_by,
                    notes,
                ))
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"API key with name '{name}' already exists")

        return api_key

    def list_api_keys(self, show_disabled: bool = False) -> List[Dict[str, Any]]:
        """List all API keys."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            if show_disabled:
                query = "SELECT * FROM api_keys ORDER BY created_at DESC"
            else:
                query = "SELECT * FROM api_keys WHERE enabled = 1 ORDER BY created_at DESC"

            cursor.execute(query)
            rows = cursor.fetchall()

            return [dict(row) for row in rows]

    def get_api_key(self, key_id: Optional[int] = None, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get API key by ID or name."""
        if not key_id and not name:
            raise ValueError("Either key_id or name must be provided")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            if key_id:
                cursor.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,))
            else:
                cursor.execute("SELECT * FROM api_keys WHERE name = ?", (name,))

            row = cursor.fetchone()
            return dict(row) if row else None

    def update_api_key(
        self,
        key_id: Optional[int] = None,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
    ):
        """Update API key status."""
        if not key_id and not name:
            raise ValueError("Either key_id or name must be provided")

        # Check if key exists
        key = self.get_api_key(key_id=key_id, name=name)
        if not key:
            raise ValueError(f"API key not found")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            if enabled is not None:
                cursor.execute(
                    "UPDATE api_keys SET enabled = ? WHERE id = ?",
                    (1 if enabled else 0, key['id'])
                )
                conn.commit()

    def delete_api_key(self, key_id: Optional[int] = None, name: Optional[str] = None):
        """Delete an API key."""
        if not key_id and not name:
            raise ValueError("Either key_id or name must be provided")

        # Check if key exists
        key = self.get_api_key(key_id=key_id, name=name)
        if not key:
            raise ValueError(f"API key not found")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM api_keys WHERE id = ?", (key['id'],))
            conn.commit()


class AuditLogManager:
    """Manages audit log operations."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    def query_audit_log(
        self,
        api_key_prefix: Optional[str] = None,
        endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query audit log with filters."""
        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            query = "SELECT * FROM audit_log WHERE 1=1"
            params = []

            if api_key_prefix:
                query += " AND api_key_prefix LIKE ?"
                params.append(f"{api_key_prefix}%")

            if endpoint:
                query += " AND endpoint LIKE ?"
                params.append(f"%{endpoint}%")

            if status_code:
                query += " AND status_code = ?"
                params.append(status_code)

            if since:
                query += " AND timestamp >= ?"
                params.append(since)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [dict(row) for row in rows]


def print_error(message: str):
    """Print error message."""
    print(f"{colors.RED}Error: {message}{colors.RESET}", file=sys.stderr)


def print_success(message: str):
    """Print success message."""
    print(f"{colors.GREEN}{message}{colors.RESET}")


def print_warning(message: str):
    """Print warning message."""
    print(f"{colors.YELLOW}{message}{colors.RESET}")


def print_info(message: str):
    """Print info message."""
    print(f"{colors.BLUE}{message}{colors.RESET}")


def format_datetime(dt_str: Optional[str]) -> str:
    """Format datetime string for display."""
    if not dt_str:
        return "Never"
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, AttributeError):
        return dt_str


def format_boolean(value: int) -> str:
    """Format boolean value for display."""
    if value:
        return f"{colors.GREEN}Yes{colors.RESET}"
    else:
        return f"{colors.RED}No{colors.RESET}"


# Command handlers

def cmd_create_api_key(args, config: ConfigManager, db: DatabaseManager):
    """Handle create-api-key command."""
    try:
        # Parse permissions
        permissions = [p.strip() for p in args.permissions.split(',')]

        # Create API key manager
        manager = APIKeyManager(db, config)

        # Create the key
        api_key = manager.create_api_key(
            name=args.name,
            permissions=permissions,
            rate_limit=args.rate_limit,
            expires=args.expires,
            created_by=os.environ.get('USER'),
        )

        # Display the key
        print()
        print(f"{colors.BOLD}{colors.GREEN}API Key Created:{colors.RESET}")
        print(f"{colors.CYAN}{api_key}{colors.RESET}")
        print()
        print(f"{colors.YELLOW}Store this key securely - it cannot be retrieved again.{colors.RESET}")
        print()
        print(f"{colors.BOLD}Details:{colors.RESET}")
        print(f"  Name: {args.name}")
        print(f"  Permissions: {', '.join(permissions)}")
        print(f"  Rate Limit: {args.rate_limit} requests/minute")
        if args.expires:
            print(f"  Expires: {format_datetime(args.expires)}")
        else:
            print(f"  Expires: Never")
        print()

    except ValueError as e:
        print_error(str(e))
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")
        sys.exit(1)


def cmd_list_api_keys(args, config: ConfigManager, db: DatabaseManager):
    """Handle list-api-keys command."""
    try:
        manager = APIKeyManager(db, config)
        keys = manager.list_api_keys(show_disabled=args.show_disabled)

        if not keys:
            print_info("No API keys found.")
            return

        # Prepare table data
        table_data = []
        for key in keys:
            table_data.append([
                key['id'],
                key['name'],
                key['permissions'],
                key['rate_limit'],
                format_datetime(key['created_at']),
                format_datetime(key['last_used_at']),
                format_boolean(key['enabled']),
            ])

        # Print table
        headers = ["ID", "Name", "Permissions", "Rate Limit", "Created", "Last Used", "Enabled"]
        print()
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        print()
        print(f"Total: {len(keys)} API key(s)")
        print()

    except Exception as e:
        print_error(f"Error listing API keys: {e}")
        sys.exit(1)


def cmd_disable_api_key(args, config: ConfigManager, db: DatabaseManager):
    """Handle disable-api-key command."""
    try:
        manager = APIKeyManager(db, config)
        manager.update_api_key(key_id=args.id, name=args.name, enabled=False)

        identifier = f"ID {args.id}" if args.id else f"'{args.name}'"
        print_success(f"API key {identifier} disabled successfully.")

    except ValueError as e:
        print_error(str(e))
        sys.exit(1)
    except Exception as e:
        print_error(f"Error disabling API key: {e}")
        sys.exit(1)


def cmd_enable_api_key(args, config: ConfigManager, db: DatabaseManager):
    """Handle enable-api-key command."""
    try:
        manager = APIKeyManager(db, config)
        manager.update_api_key(key_id=args.id, name=args.name, enabled=True)

        identifier = f"ID {args.id}" if args.id else f"'{args.name}'"
        print_success(f"API key {identifier} enabled successfully.")

    except ValueError as e:
        print_error(str(e))
        sys.exit(1)
    except Exception as e:
        print_error(f"Error enabling API key: {e}")
        sys.exit(1)


def cmd_delete_api_key(args, config: ConfigManager, db: DatabaseManager):
    """Handle delete-api-key command."""
    try:
        # Require confirmation
        if args.confirm != "DELETE":
            print_error("You must pass --confirm DELETE to delete an API key")
            sys.exit(1)

        manager = APIKeyManager(db, config)

        # Get the key first to show what we're deleting
        key = manager.get_api_key(key_id=args.id, name=args.name)
        if not key:
            print_error("API key not found")
            sys.exit(1)

        # Delete it
        manager.delete_api_key(key_id=args.id, name=args.name)

        identifier = f"ID {args.id}" if args.id else f"'{args.name}'"
        print_success(f"API key {identifier} ('{key['name']}') deleted successfully.")

    except ValueError as e:
        print_error(str(e))
        sys.exit(1)
    except Exception as e:
        print_error(f"Error deleting API key: {e}")
        sys.exit(1)


def cmd_audit_log(args, config: ConfigManager, db: DatabaseManager):
    """Handle audit-log command."""
    try:
        manager = AuditLogManager(db)

        logs = manager.query_audit_log(
            api_key_prefix=args.api_key,
            endpoint=args.endpoint,
            status_code=args.status,
            since=args.since,
            limit=args.limit,
        )

        if not logs:
            print_info("No audit log entries found.")
            return

        # Prepare table data
        table_data = []
        for log in logs:
            table_data.append([
                format_datetime(log['timestamp']),
                log['api_key_prefix'],
                log['source_ip'],
                log['method'],
                log['endpoint'],
                log['status_code'],
                f"{log['response_time_ms']:.2f}",
            ])

        # Print table
        headers = ["Timestamp", "API Key", "Source IP", "Method", "Endpoint", "Status", "Time (ms)"]
        print()
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
        print()
        print(f"Total: {len(logs)} log entry/entries")
        print()

    except Exception as e:
        print_error(f"Error querying audit log: {e}")
        sys.exit(1)


def cmd_init_db(args, config: ConfigManager, db: DatabaseManager):
    """Handle init-db command."""
    try:
        db.init_db()
    except Exception as e:
        print_error(f"Error initializing database: {e}")
        sys.exit(1)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Ceph Management REST API - CLI Management Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--config',
        help='Path to config.yaml file',
        default=None,
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # create-api-key command
    create_parser = subparsers.add_parser(
        'create-api-key',
        help='Create a new API key',
    )
    create_parser.add_argument(
        '--name',
        required=True,
        help='Name/description for the key',
    )
    create_parser.add_argument(
        '--permissions',
        required=True,
        help='Comma-separated list of permissions',
    )
    create_parser.add_argument(
        '--rate-limit',
        type=int,
        default=60,
        help='Requests per minute (default: 60)',
    )
    create_parser.add_argument(
        '--expires',
        help='Expiration date in ISO format (optional)',
    )

    # list-api-keys command
    list_parser = subparsers.add_parser(
        'list-api-keys',
        help='List all API keys',
    )
    list_parser.add_argument(
        '--show-disabled',
        action='store_true',
        help='Include disabled keys',
    )

    # disable-api-key command
    disable_parser = subparsers.add_parser(
        'disable-api-key',
        help='Disable an API key',
    )
    disable_group = disable_parser.add_mutually_exclusive_group(required=True)
    disable_group.add_argument('--id', type=int, help='API key ID')
    disable_group.add_argument('--name', help='API key name')

    # enable-api-key command
    enable_parser = subparsers.add_parser(
        'enable-api-key',
        help='Enable a disabled API key',
    )
    enable_group = enable_parser.add_mutually_exclusive_group(required=True)
    enable_group.add_argument('--id', type=int, help='API key ID')
    enable_group.add_argument('--name', help='API key name')

    # delete-api-key command
    delete_parser = subparsers.add_parser(
        'delete-api-key',
        help='Delete an API key',
    )
    delete_group = delete_parser.add_mutually_exclusive_group(required=True)
    delete_group.add_argument('--id', type=int, help='API key ID')
    delete_group.add_argument('--name', help='API key name')
    delete_parser.add_argument(
        '--confirm',
        required=True,
        help='Must type "DELETE" to confirm',
    )

    # audit-log command
    audit_parser = subparsers.add_parser(
        'audit-log',
        help='Query audit log',
    )
    audit_parser.add_argument(
        '--api-key',
        help='Filter by API key prefix',
    )
    audit_parser.add_argument(
        '--endpoint',
        help='Filter by endpoint',
    )
    audit_parser.add_argument(
        '--status',
        type=int,
        help='Filter by HTTP status code',
    )
    audit_parser.add_argument(
        '--since',
        help='Show entries since datetime (ISO format)',
    )
    audit_parser.add_argument(
        '--limit',
        type=int,
        default=100,
        help='Max entries to show (default: 100)',
    )

    # init-db command
    init_parser = subparsers.add_parser(
        'init-db',
        help='Initialize the database',
    )

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Load configuration
    config = ConfigManager(args.config)

    # Initialize database manager
    db_path = config.get_db_path()
    db = DatabaseManager(db_path)

    # Route to command handler
    if args.command == 'create-api-key':
        cmd_create_api_key(args, config, db)
    elif args.command == 'list-api-keys':
        cmd_list_api_keys(args, config, db)
    elif args.command == 'disable-api-key':
        cmd_disable_api_key(args, config, db)
    elif args.command == 'enable-api-key':
        cmd_enable_api_key(args, config, db)
    elif args.command == 'delete-api-key':
        cmd_delete_api_key(args, config, db)
    elif args.command == 'audit-log':
        cmd_audit_log(args, config, db)
    elif args.command == 'init-db':
        cmd_init_db(args, config, db)
    else:
        print_error(f"Unknown command: {args.command}")
        sys.exit(1)


if __name__ == '__main__':
    main()
