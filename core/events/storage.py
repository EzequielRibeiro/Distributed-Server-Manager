from __future__ import annotations

from typing import Protocol

from .models import UniversalEvent


class EventStore(Protocol):
    """Persistence boundary for Universal Event Platform events."""

    def store(self, event: UniversalEvent) -> None:
        """Persist one validated immutable event."""

    def get(self, event_id: str) -> UniversalEvent | None:
        """Return one previously persisted universal event, if present."""
