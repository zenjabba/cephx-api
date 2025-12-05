"""Application configuration using pydantic-settings."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseSettings):
    """Server configuration."""

    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")
    workers: int = Field(default=4, ge=1, description="Number of worker processes")
    reload: bool = Field(default=False, description="Enable auto-reload for development")
    log_level: str = Field(default="info", description="Logging level")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level."""
        valid_levels = ["debug", "info", "warning", "error", "critical"]
        if v.lower() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.lower()


class DatabaseConfig(BaseSettings):
    """Database configuration."""

    path: str = Field(default="./data/cephx-api.db", description="SQLite database file path")
    backup_path: Union[str, None] = Field(None, description="Database backup directory")
    backup_interval_hours: int = Field(default=24, ge=1, description="Backup interval in hours")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """Ensure parent directory exists."""
        path = Path(v)
        path.parent.mkdir(parents=True, exist_ok=True)
        return v


class RateLimitConfig(BaseSettings):
    """Rate limiting configuration."""

    enabled: bool = Field(default=True, description="Enable rate limiting")
    requests_per_minute: int = Field(default=60, ge=1, description="Requests per minute per API key")
    burst_size: int = Field(default=10, ge=1, description="Burst size for rate limiting")


class CephConfig(BaseSettings):
    """Ceph configuration."""

    binary_path: str = Field(default="/usr/bin/ceph", description="Path to ceph binary")
    config_file: Union[str, None] = Field(None, description="Path to ceph.conf")
    keyring_file: Union[str, None] = Field(None, description="Path to keyring file")
    user: str = Field(default="admin", description="Ceph user for authentication")
    command_timeout: int = Field(default=30, ge=1, description="Command timeout in seconds")
    connection_timeout: int = Field(default=5, ge=1, description="Connection timeout in seconds")
    filesystem_name: str = Field(default="cephfs", description="Default CephFS filesystem name")

    @field_validator("binary_path", "config_file", "keyring_file")
    @classmethod
    def validate_file_path(cls, v: Union[str, None]) -> Union[str, None]:
        """Validate file paths exist."""
        if v is None:
            return v
        path = Path(v)
        # Only validate if it's the binary path and it doesn't exist
        if "binary" in cls.model_fields and not path.exists():
            logging.warning(f"Ceph binary not found at {v}")
        return v


class CORSConfig(BaseSettings):
    """CORS configuration."""

    enabled: bool = Field(default=True, description="Enable CORS")
    allow_origins: List[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed origins",
    )
    allow_credentials: bool = Field(default=True, description="Allow credentials")
    allow_methods: List[str] = Field(default=["GET", "POST", "PUT", "DELETE", "PATCH"], description="Allowed methods")
    allow_headers: List[str] = Field(default=["*"], description="Allowed headers")


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    level: str = Field(default="info", description="Default logging level")
    format: str = Field(
        default="json",
        description="Log format (json or text)",
    )
    file_path: Union[str, None] = Field(None, description="Log file path")
    max_bytes: int = Field(default=10485760, description="Max log file size (10MB)")
    backup_count: int = Field(default=5, description="Number of backup log files")

    @field_validator("level")
    @classmethod
    def validate_level(cls, v: str) -> str:
        """Validate logging level."""
        valid_levels = ["debug", "info", "warning", "error", "critical"]
        if v.lower() not in valid_levels:
            raise ValueError(f"level must be one of {valid_levels}")
        return v.lower()

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        """Validate log format."""
        if v.lower() not in ["json", "text"]:
            raise ValueError("format must be 'json' or 'text'")
        return v.lower()


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_prefix="CEPHX_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # Sub-configurations
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    ceph: CephConfig = Field(default_factory=CephConfig)
    cors: CORSConfig = Field(default_factory=CORSConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Top-level settings
    environment: str = Field(default="production", description="Environment (development/production)")
    debug: bool = Field(default=False, description="Debug mode")
    config_file: Union[str, None] = Field(default="config.yaml", description="Path to configuration file")

    @classmethod
    def load_from_yaml(cls, config_path: Union[str, Path]) -> "Settings":
        """Load settings from YAML file.

        Args:
            config_path: Path to YAML configuration file

        Returns:
            Settings instance with values from YAML and environment

        Raises:
            FileNotFoundError: If config file not found
            yaml.YAMLError: If YAML parsing fails
        """
        config_path = Path(config_path)

        if not config_path.exists():
            logging.warning(f"Config file not found: {config_path}, using defaults")
            return cls()

        try:
            with open(config_path) as f:
                config_data = yaml.safe_load(f) or {}

            # Flatten nested config for pydantic-settings
            return cls(**config_data)

        except yaml.YAMLError as e:
            logging.error(f"Failed to parse YAML config: {e}")
            raise
        except Exception as e:
            logging.error(f"Failed to load config: {e}")
            raise

    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary.

        Returns:
            Dictionary representation of settings
        """
        return self.model_dump()


# Global settings instance
_settings: Union[Settings, None] = None


def get_settings() -> Settings:
    """Get application settings singleton.

    Returns:
        Settings instance
    """
    global _settings

    if _settings is None:
        config_file = Path("config.yaml")
        if config_file.exists():
            _settings = Settings.load_from_yaml(config_file)
        else:
            _settings = Settings()

    return _settings


def reload_settings(config_path: Union[str, Path, None] = None) -> Settings:
    """Reload settings from configuration file.

    Args:
        config_path: Path to configuration file (optional)

    Returns:
        Reloaded Settings instance
    """
    global _settings

    if config_path:
        _settings = Settings.load_from_yaml(config_path)
    else:
        config_file = Path("config.yaml")
        if config_file.exists():
            _settings = Settings.load_from_yaml(config_file)
        else:
            _settings = Settings()

    return _settings
