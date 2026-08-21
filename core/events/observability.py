from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from threading import RLock
from typing import Callable

from .models import UniversalEvent


EventSink = Callable[[UniversalEvent], None]


@dataclass(frozen=True)
class EventPlatformSnapshot:
    published_total: int
    failed_total: int
    by_type: dict[str, int]
    by_severity: dict[str, int]
    last_event_id: str | None
    last_event_type: str | None
    last_event_timestamp: str | None

    @property
    def healthy(self) -> bool:
        return self.failed_total == 0


class EventPlatformMetrics:
    """Thread-safe in-process observability counters for event publication."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._published_total = 0
        self._failed_total = 0
        self._by_type: Counter[str] = Counter()
        self._by_severity: Counter[str] = Counter()
        self._last_event: UniversalEvent | None = None

    def record_published(self, event: UniversalEvent) -> None:
        with self._lock:
            self._published_total += 1
            self._by_type[event.type] += 1
            self._by_severity[event.severity.value] += 1
            self._last_event = event

    def record_failed(self) -> None:
        with self._lock:
            self._failed_total += 1

    def snapshot(self) -> EventPlatformSnapshot:
        with self._lock:
            last = self._last_event
            timestamp = None
            if last is not None:
                timestamp = str(last.to_dict()["timestamp"])
            return EventPlatformSnapshot(
                published_total=self._published_total,
                failed_total=self._failed_total,
                by_type=dict(self._by_type),
                by_severity=dict(self._by_severity),
                last_event_id=last.id if last else None,
                last_event_type=last.type if last else None,
                last_event_timestamp=timestamp,
            )


class ObservedEventSink:
    """Wraps a sink and records success/failure without swallowing errors."""

    def __init__(self, sink: EventSink, metrics: EventPlatformMetrics) -> None:
        self._sink = sink
        self._metrics = metrics

    def __call__(self, event: UniversalEvent) -> None:
        try:
            self._sink(event)
        except Exception:
            self._metrics.record_failed()
            raise
        self._metrics.record_published(event)


__all__ = ["EventPlatformMetrics", "EventPlatformSnapshot", "ObservedEventSink"]
