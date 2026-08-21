#!/usr/bin/env python3
"""Base contract for game-agnostic instance runtime adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AdapterError(RuntimeError):
    """Raised when a runtime adapter cannot safely complete an operation."""


class InstanceRuntimeAdapter(ABC):
    name = "base"

    @abstractmethod
    def status(self, instance: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def start(self, instance: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def stop(self, instance: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def restart(self, instance: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def doctor(self, instance: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def broadcast(self, instance: dict[str, Any], message: str, *, priority: str = "normal") -> dict[str, Any]:
        """Deliver a player-visible message or fail closed when unsupported.

        Game-specific adapters may override this method. The Controller never sends
        shell commands or RCON credentials through the universal broadcast contract.
        """
        raise AdapterError(f"runtime adapter {self.name} does not support broadcast")


__all__ = ["AdapterError", "InstanceRuntimeAdapter"]
