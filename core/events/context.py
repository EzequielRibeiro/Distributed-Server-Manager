from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from .models import UniversalEvent


@dataclass(frozen=True)
class EventContext:
    """Correlation and causation metadata shared across an event workflow."""

    correlation_id: str
    causation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, str) or not self.correlation_id.strip():
            raise ValueError("correlation_id must not be empty")
        if self.causation_id is not None:
            if not isinstance(self.causation_id, str) or not self.causation_id.strip():
                raise ValueError("causation_id must not be empty")

    @classmethod
    def root(cls, correlation_id: Optional[str] = None) -> "EventContext":
        """Create a root workflow context with no causal parent."""

        return cls(
            correlation_id=correlation_id or f"corr_{uuid4().hex}",
        )

    @classmethod
    def from_event(cls, event: UniversalEvent) -> "EventContext":
        """Create a child context caused by an already published event.

        Events created before correlation helpers existed may not have a
        correlation identifier. In that case derive a stable correlation id
        from the parent event id so every descendant remains in one chain.
        """

        correlation_id = event.correlation_id
        if correlation_id is None:
            suffix = event.id.removeprefix("evt_")
            correlation_id = f"corr_{suffix}"

        return cls(
            correlation_id=correlation_id,
            causation_id=event.id,
        )

    def caused_by(self, event: UniversalEvent) -> "EventContext":
        """Return the same workflow correlation with a new causal parent."""

        return EventContext(
            correlation_id=self.correlation_id,
            causation_id=event.id,
        )
