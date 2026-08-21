from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .models import UniversalEvent


class TimelineEventSource(Protocol):
    def list_events(self, **filters: Any) -> list[UniversalEvent]: ...


@dataclass(frozen=True)
class TimelineEntry:
    id: str
    type: str
    timestamp: str
    severity: str
    source_type: str
    source_id: str
    correlation_id: str | None
    causation_id: str | None
    scope: dict[str, str]
    data: dict[str, Any]

    @classmethod
    def from_event(cls, event: UniversalEvent) -> "TimelineEntry":
        payload = event.to_dict()
        return cls(
            id=event.id,
            type=event.type,
            timestamp=str(payload["timestamp"]),
            severity=event.severity.value,
            source_type=event.source.type,
            source_id=event.source.id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            scope=event.scope.to_dict(),
            data=dict(event.data),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "timestamp": self.timestamp,
            "severity": self.severity,
            "source": {"type": self.source_type, "id": self.source_id},
            "scope": dict(self.scope),
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "data": dict(self.data),
        }


class TimelineConsumer:
    """Read model for timeline views backed exclusively by universal events."""

    def __init__(self, event_source: TimelineEventSource) -> None:
        self._event_source = event_source

    def entries(
        self,
        *,
        controller_id: str | None = None,
        agent_id: str | None = None,
        customer_id: str | None = None,
        instance_id: str | None = None,
        correlation_id: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
        newest_first: bool = True,
    ) -> list[TimelineEntry]:
        events = self._event_source.list_events(
            controller_id=controller_id,
            agent_id=agent_id,
            customer_id=customer_id,
            instance_id=instance_id,
            correlation_id=correlation_id,
            event_type=event_type,
            limit=limit,
            newest_first=newest_first,
        )
        return [TimelineEntry.from_event(event) for event in events]


__all__ = ["TimelineConsumer", "TimelineEntry", "TimelineEventSource"]
