#!/usr/bin/env python3
"""Database backend selection for Capivara DSM."""

from __future__ import annotations

from backend import DatabaseBackend, DatabaseConfig, DatabaseConfigurationError

SUPPORTED_DATABASE_DRIVERS = ("sqlite", "postgresql", "mysql")

DATABASE_DRIVER_ALIASES = {
    "sqlite3": "sqlite",
    "postgres": "postgresql",
    "pgsql": "postgresql",
    "mariadb": "mysql",
}


def normalize_database_driver(driver: str) -> str:
    if not isinstance(driver, str):
        raise DatabaseConfigurationError("database driver must be a string")
    normalized = driver.strip().lower()
    if not normalized:
        raise DatabaseConfigurationError("database driver is required")
    normalized = DATABASE_DRIVER_ALIASES.get(normalized, normalized)
    if normalized not in SUPPORTED_DATABASE_DRIVERS:
        raise DatabaseConfigurationError(
            "unsupported database driver: "
            f"{driver}. Supported drivers: " + ", ".join(SUPPORTED_DATABASE_DRIVERS)
        )
    return normalized


def canonicalize_database_config(config: DatabaseConfig) -> DatabaseConfig:
    normalized_driver = normalize_database_driver(config.driver)
    if normalized_driver == config.driver:
        return config
    return DatabaseConfig(
        driver=normalized_driver,
        database=config.database,
        host=config.host,
        port=config.port,
        user=config.user,
        password_file=config.password_file,
        tls_mode=config.tls_mode,
        connect_timeout=config.connect_timeout,
    )


def create_backend(config: DatabaseConfig) -> DatabaseBackend:
    """Instantiate the configured migration-free Baseline v2 backend."""
    config = canonicalize_database_config(config)
    if config.driver == "sqlite":
        from backends.baseline_sqlite_backend import BaselineSQLiteBackend

        return BaselineSQLiteBackend(config)
    if config.driver == "postgresql":
        try:
            from backends.baseline_postgresql_backend import BaselinePostgreSQLBackend
        except ImportError as exc:
            raise DatabaseConfigurationError(
                "PostgreSQL backend is not installed yet"
            ) from exc
        return BaselinePostgreSQLBackend(config)
    if config.driver == "mysql":
        try:
            from backends.baseline_mysql_backend import BaselineMySQLBackend
        except ImportError as exc:
            raise DatabaseConfigurationError(
                "MySQL/MariaDB backend is not installed yet"
            ) from exc
        return BaselineMySQLBackend(config)
    raise DatabaseConfigurationError(f"unsupported database driver: {config.driver}")
