"""Universal Event Platform public contract.

Producers should depend on this package instead of dashboard, alert, timeline,
or storage implementations.
"""

from .models import EventScope, EventSeverity, EventSource, UniversalEvent
from .publisher import EventPublisher, publish
from .registry import EVENT_TYPES, is_registered, require_registered
from .validator import EventValidationError, validate_event

__all__ = [
    "EVENT_TYPES",
    "EventPublisher",
    "EventScope",
    "EventSeverity",
    "EventSource",
    "EventValidationError",
    "UniversalEvent",
    "is_registered",
    "publish",
    "require_registered",
    "validate_event",
]
