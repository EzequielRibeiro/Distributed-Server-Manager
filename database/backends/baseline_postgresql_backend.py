#!/usr/bin/env python3
"""PostgreSQL backend using Database Baseline v2."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping, Sequence

import postgresql_engine
from baseline_backend_runtime import baseline_status, initialize_baseline, validate_baseline
from backends.postgresql_backend import PostgreSQLBackend


def _json_text_loads(value: Any) -> str:
    """Keep PostgreSQL JSON values backend-neutral at repository boundaries.

    SQLite and MySQL/MariaDB expose the Capivara JSON columns as serialized
    JSON text. Psycopg normally decodes json/jsonb into Python objects, which
    made repository behavior depend on the selected database driver. Baseline
    v2 uses text as the common persistence contract; repositories explicitly
    decode JSON when they need structured values.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8")
    return str(value)


def _configure_json_boundary(connection: Any) -> None:
    try:
        from psycopg.types.json import set_json_loads
    except ImportError as exc:  # pragma: no cover - backend dependency guard
        raise RuntimeError("psycopg JSON adapter is unavailable") from exc
    set_json_loads(_json_text_loads, connection)


class BaselinePostgreSQLBackend(PostgreSQLBackend):
    @contextmanager
    def connect(self) -> Iterator[Any]:
        """Open PostgreSQL with Baseline v2 backend-neutral JSON decoding."""
        connection = postgresql_engine.connect(self.config)
        _configure_json_boundary(connection)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Open an atomic transaction with backend-neutral JSON decoding."""
        connection = postgresql_engine.connect(self.config)
        _configure_json_boundary(connection)
        try:
            with connection.transaction():
                yield connection
        finally:
            connection.close()

    def initialize(self) -> Mapping[str, Any]:
        return initialize_baseline(self)

    def migrate(self) -> Mapping[str, Any]:
        return validate_baseline(self)

    def status(self) -> Mapping[str, Any]:
        return baseline_status(self)

    def health_check(self) -> Mapping[str, Any]:
        return validate_baseline(self)

    def current_schema_version(self) -> int:
        # Kept only for DatabaseBackend compatibility. Baseline v2 is identified
        # by name + checksum, never by a migration version.
        return 0

    def applied_migrations(self) -> Sequence[Mapping[str, Any]]:
        return []


__all__ = ["BaselinePostgreSQLBackend"]
