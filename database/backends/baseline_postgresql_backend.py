#!/usr/bin/env python3
"""PostgreSQL backend using Database Baseline v2."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from baseline_backend_runtime import baseline_status, initialize_baseline, validate_baseline
from backends.postgresql_backend import PostgreSQLBackend


class BaselinePostgreSQLBackend(PostgreSQLBackend):
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
