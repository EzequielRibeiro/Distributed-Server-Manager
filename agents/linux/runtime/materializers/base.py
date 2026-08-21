#!/usr/bin/env python3
"""Materializer contract for Agent-owned instance runtimes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MaterializerError(RuntimeError):
    pass


class InstanceRuntimeMaterializer(ABC):
    name = "base"

    @abstractmethod
    def inspect(self, spec: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def apply(self, spec: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def remove(self, spec: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


__all__ = ["InstanceRuntimeMaterializer", "MaterializerError"]
