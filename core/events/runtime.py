from __future__ import annotations

from typing import Callable

from .alerts import AlertConsumer
from .automation import AutomationEngine
from .models import UniversalEvent
from .observability import EventPlatformMetrics, EventPlatformSnapshot, ObservedEventSink
from .publisher import EventPublisher
from .streaming import CompositeEventSink, EventStreamHub


EventSink = Callable[[UniversalEvent], None]


class EventPlatformRuntime:
    """Application composition root for Universal Event Platform consumers.

    Persistence always runs first. Secondary consumers then receive the same
    immutable event. Transport-specific streaming and alert persistence remain
    adapters outside this core runtime.
    """

    def __init__(
        self,
        store: EventSink,
        *,
        stream: EventStreamHub | None = None,
        alerts: AlertConsumer | None = None,
        automation: AutomationEngine | None = None,
        metrics: EventPlatformMetrics | None = None,
    ) -> None:
        self.stream = stream or EventStreamHub()
        self.alerts = alerts or AlertConsumer()
        self.automation = automation or AutomationEngine()
        self.metrics = metrics or EventPlatformMetrics()

        fanout = CompositeEventSink((
            store,
            self.stream.publish,
            self.alerts,
            self.automation.handle,
        ))
        self.publisher = EventPublisher(
            sink=ObservedEventSink(fanout, self.metrics),
        )

    def snapshot(self) -> EventPlatformSnapshot:
        return self.metrics.snapshot()


__all__ = ["EventPlatformRuntime"]
