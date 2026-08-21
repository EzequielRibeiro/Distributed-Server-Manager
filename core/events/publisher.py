from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .context import EventContext
from .models import EventScope, EventSeverity, EventSource, UniversalEvent
from .validator import validate_event


EventSink = Callable[[UniversalEvent], None]


class EventPublisher:
    """Builds, validates and dispatches events to an optional sink.

    The publisher stays transport- and persistence-agnostic. Correlation may be
    supplied either through an EventContext or through the legacy explicit
    correlation_id/causation_id parameters.
    """

    def __init__(self, sink: Optional[EventSink] = None) -> None:
        self._sink = sink

    def publish(
        self,
        event_type: str,
        *,
        source: EventSource,
        severity: EventSeverity = EventSeverity.INFO,
        scope: Optional[EventScope] = None,
        data: Optional[Dict[str, Any]] = None,
        version: int = 1,
        context: Optional[EventContext] = None,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
    ) -> UniversalEvent:
        if context is not None:
            if correlation_id is not None or causation_id is not None:
                raise ValueError(
                    "context cannot be combined with explicit "
                    "correlation_id or causation_id"
                )
            correlation_id = context.correlation_id
            causation_id = context.causation_id

        event = UniversalEvent(
            type=event_type,
            source=source,
            severity=severity,
            scope=scope or EventScope(),
            data=dict(data or {}),
            version=version,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        validate_event(event)

        if self._sink is not None:
            self._sink(event)

        return event


_default_publisher = EventPublisher()


def publish(
    event_type: str,
    *,
    source: EventSource,
    severity: EventSeverity = EventSeverity.INFO,
    scope: Optional[EventScope] = None,
    data: Optional[Dict[str, Any]] = None,
    version: int = 1,
    context: Optional[EventContext] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
) -> UniversalEvent:
    return _default_publisher.publish(
        event_type,
        source=source,
        severity=severity,
        scope=scope,
        data=data,
        version=version,
        context=context,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )
