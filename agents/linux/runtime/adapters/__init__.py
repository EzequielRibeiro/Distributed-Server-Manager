"""Game-agnostic instance runtime adapters."""

from .base import AdapterError, InstanceRuntimeAdapter
from .registry import resolve_adapter

__all__ = ["AdapterError", "InstanceRuntimeAdapter", "resolve_adapter"]
