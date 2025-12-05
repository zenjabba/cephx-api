"""Application configuration."""

from functools import lru_cache
from typing import Dict, List, Literal
from typing import Union

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API Settings
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "production"

    # Security
    api_key_header: str = "X-API-Key"
    api_keys: Dict[str, Dict[str, Union[str, List[str]]]] = Field(
        default_factory=lambda: {
            "admin-key": {"name": "admin", "permissions": ["fs:read", "fs:write", "pool:read", "pool:write", "cluster:read", "auth:read", "auth:write"]},
            "readonly-key": {"name": "readonly", "permissions": ["fs:read", "pool:read", "cluster:read", "auth:read"]},
        }
    )

    # Ceph Settings
    ceph_config_file: str = "/etc/ceph/ceph.conf"
    ceph_keyring: str = "/etc/ceph/ceph.client.admin.keyring"
    ceph_user: str = "admin"
    ceph_command_timeout: int = 30

    # Filesystem Defaults
    default_crush_rule: str = "replicated_mach2"
    default_meta_pool_pg: int = 16
    default_data_pool_type: str = "replicated"
    default_enable_snapshots: bool = True

    # Logging
    log_level: str = "INFO"
    audit_log_enabled: bool = True
    audit_log_file: str = "/var/log/cephx-api/audit.log"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
