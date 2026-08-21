"""Universal Event Platform public contract.

Producers should depend on this package instead of dashboard, alert, timeline,
or storage implementations.
"""

from .context import EventContext
from .models import EventScope, EventSeverity, EventSource, UniversalEvent
from .publisher import EventPublisher, publish
from .registry import EVENT_TYPES, is_registered, require_registered
from .storage import EventStore
from .timeline import TimelineConsumer, TimelineEntry, TimelineEventSource
from .validator import EventValidationError, validate_event

__all__ = [
    "EVENT_TYPES",
    "EventContext",
    "EventPublisher",
    "EventScope",
    "EventSeverity",
    "EventSource",
    "EventStore",
    "EventValidationError",
    "TimelineConsumer",
    "TimelineEntry",
    "TimelineEventSource",
    "UniversalEvent",
    "is_registered",
    "publish",
    "require_registered",
    "validate_event",
]
