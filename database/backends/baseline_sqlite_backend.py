#!/usr/bin/env python3
"""SQLite backend using Database Baseline v2."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from baseline_backend_runtime import baseline_status, initialize_baseline, validate_baseline
from backends.sqlite_backend import SQLiteBackend


class BaselineSQLiteBackend(SQLiteBackend):
    def initialize(self) -> Mapping[str, Any]:
        return initialize_baseline(self)

    def migrate(self) -> Mapping[str, Any]:
        # Reconcile first, then return the strict health payload expected by the
        # manager `migrate` command (including `valid`).
        initialize_baseline(self)
        return validate_baseline(self)

    def status(self) -> Mapping[str, Any]:
        return baseline_status(self)

    def health_check(self) -> Mapping[str, Any]:
        return validate_baseline(self)

    def current_schema_version(self) -> int:
        return 0

    def applied_migrations(self) -> Sequence[Mapping[str, Any]]:
        return []


__all__ = ["BaselineSQLiteBackend"]
