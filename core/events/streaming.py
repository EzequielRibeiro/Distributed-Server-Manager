from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Iterable

from .models import UniversalEvent


EventSubscriber = Callable[[UniversalEvent], None]
EventSink = Callable[[UniversalEvent], None]


@dataclass(frozen=True)
class Subscription:
    id: int


class EventStreamHub:
    """Process-local fan-out boundary for SSE/WebSocket adapters.

    Network transports intentionally stay outside the core event package. This
    hub provides a thread-safe subscription primitive that transport adapters
    can consume without coupling producers to HTTP/WebSocket implementations.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._next_id = 1
        self._subscribers: dict[int, EventSubscriber] = {}

    def subscribe(self, subscriber: EventSubscriber) -> Subscription:
        if not callable(subscriber):
            raise TypeError("subscriber must be callable")
        with self._lock:
            subscription = Subscription(self._next_id)
            self._next_id += 1
            self._subscribers[subscription.id] = subscriber
        return subscription

    def unsubscribe(self, subscription: Subscription) -> bool:
        with self._lock:
            return self._subscribers.pop(subscription.id, None) is not None

    def publish(self, event: UniversalEvent) -> None:
        with self._lock:
            subscribers = tuple(self._subscribers.values())
        for subscriber in subscribers:
            subscriber(event)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


class CompositeEventSink:
    """Fan one event out to multiple independent consumers in order."""

    def __init__(self, sinks: Iterable[EventSink]) -> None:
        self._sinks = tuple(sinks)

    def __call__(self, event: UniversalEvent) -> None:
        for sink in self._sinks:
            sink(event)


__all__ = [
    "CompositeEventSink",
    "EventSink",
    "EventStreamHub",
    "EventSubscriber",
    "Subscription",
]
