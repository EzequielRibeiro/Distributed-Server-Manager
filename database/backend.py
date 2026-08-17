#!/usr/bin/env python3
"""Common database backend contract for Capivara DSM."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class DatabaseError(RuntimeError):
    """Base error for Capivara database operations."""


class DatabaseConfigurationError(DatabaseError):
    """Invalid or incomplete backend configuration."""


class DatabaseConnectionError(DatabaseError):
    """Database connection could not be established."""


class DatabaseMigrationError(DatabaseError):
    """Database migration could not be completed."""


@dataclass(frozen=True)
class DatabaseConfig:
    """Backend-independent database configuration."""

    driver: str
    database: str

    host: str | None = None
    port: int | None = None
    user: str | None = None

    password_file: str | None = None

    tls_mode: str = "preferred"
    connect_timeout: int = 5


class DatabaseBackend(ABC):
    """Common database contract for Capivara DSM."""

    name: str

    def __init__(self, config: DatabaseConfig):
        self.config = config

    @abstractmethod
    def connect(self) -> AbstractContextManager[Any]:
        """Return a managed database connection."""

    @abstractmethod
    def transaction(self) -> AbstractContextManager[Any]:
        """Return an atomic backend-specific transaction."""

    @abstractmethod
    def initialize(self) -> Mapping[str, Any]:
        """Initialize database and apply pending migrations."""

    @abstractmethod
    def migrate(self) -> Mapping[str, Any]:
        """Apply pending migrations."""

    @abstractmethod
    def status(self) -> Mapping[str, Any]:
        """Return database and migration status."""

    @abstractmethod
    def health_check(self) -> Mapping[str, Any]:
        """Validate connectivity and database health."""

    @abstractmethod
    def current_schema_version(self) -> int:
        """Return current applied migration version."""

    @abstractmethod
    def applied_migrations(
        self,
    ) -> Sequence[Mapping[str, Any]]:
        """Return migrations already applied."""

    @abstractmethod
    def backup(self, destination: str) -> Mapping[str, Any]:
        """Create a backend-appropriate consistent backup."""

    @abstractmethod
    def restore(self, source: str) -> Mapping[str, Any]:
        """Restore a backend-appropriate backup."""

    @abstractmethod
    def close(self) -> None:
        """Release backend resources or pools."""
