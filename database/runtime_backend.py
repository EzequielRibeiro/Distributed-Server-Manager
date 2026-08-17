#!/usr/bin/env python3
"""Runtime database configuration for Capivara DSM services."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

import sqlite_engine

from backend import (
    DatabaseBackend,
    DatabaseConfig,
    DatabaseConfigurationError,
)
from backend_factory import (
    create_backend,
    normalize_database_driver,
)


DEFAULT_DATABASE_NAME = "capivara"
DEFAULT_TLS_MODE = "preferred"
DEFAULT_CONNECT_TIMEOUT = 5

DEFAULT_PORTS = {
    "postgresql": 5432,
    "mysql": 3306,
}


def _optional_value(
    environment: Mapping[str, str],
    name: str,
) -> str | None:
    """Return a stripped non-empty environment value."""

    value = environment.get(name)

    if value is None:
        return None

    value = value.strip()

    return value or None


def _network_port(
    environment: Mapping[str, str],
    driver: str,
) -> int:
    """Return a validated configured or driver-default port."""

    value = _optional_value(
        environment,
        "DSM_DATABASE_PORT",
    )

    if value is None:
        return DEFAULT_PORTS[driver]

    try:
        port = int(value)

    except ValueError as exc:
        raise DatabaseConfigurationError(
            "DSM_DATABASE_PORT must be an integer"
        ) from exc

    if not 1 <= port <= 65535:
        raise DatabaseConfigurationError(
            "DSM_DATABASE_PORT must be between 1 and 65535"
        )

    return port


def database_config_from_environment(
    environment: Mapping[str, str] | None = None,
) -> DatabaseConfig:
    """Build the runtime database config from DSM environment variables."""

    environment = os.environ if environment is None else environment

    driver = normalize_database_driver(
        environment.get(
            "DSM_DATABASE_DRIVER",
            "sqlite",
        )
    )

    if driver == "sqlite":
        configured_database = _optional_value(
            environment,
            "DSM_DATABASE",
        )

        database = (
            Path(configured_database).expanduser().resolve()
            if configured_database is not None
            else sqlite_engine.default_database(
                sqlite_engine.default_root()
            ).resolve()
        )

        return DatabaseConfig(
            driver="sqlite",
            database=str(database),
            connect_timeout=DEFAULT_CONNECT_TIMEOUT,
        )

    database = (
        _optional_value(
            environment,
            "DSM_DATABASE_NAME",
        )
        or DEFAULT_DATABASE_NAME
    )
    host = _optional_value(
        environment,
        "DSM_DATABASE_HOST",
    )
    user = _optional_value(
        environment,
        "DSM_DATABASE_USER",
    )

    if host is None:
        raise DatabaseConfigurationError(
            f"{driver} requires DSM_DATABASE_HOST"
        )

    if user is None:
        raise DatabaseConfigurationError(
            f"{driver} requires DSM_DATABASE_USER"
        )

    tls_mode = (
        _optional_value(
            environment,
            "DSM_DATABASE_TLS",
        )
        or DEFAULT_TLS_MODE
    ).lower()

    return DatabaseConfig(
        driver=driver,
        database=database,
        host=host,
        port=_network_port(
            environment,
            driver,
        ),
        user=user,
        password_file=_optional_value(
            environment,
            "DSM_DATABASE_PASSWORD_FILE",
        ),
        tls_mode=tls_mode,
        connect_timeout=DEFAULT_CONNECT_TIMEOUT,
    )


def backend_from_environment(
    environment: Mapping[str, str] | None = None,
) -> DatabaseBackend:
    """Create the database backend selected by the runtime environment."""

    return create_backend(
        database_config_from_environment(
            environment
        )
    )
