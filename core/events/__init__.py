"""Universal Event Platform public contract.

Phase 21 starts with a transport- and persistence-agnostic event envelope.
Producers should depend on this package instead of dashboard, alert, timeline,
or storage implementations.
"""

from .models import EventScope, EventSeverity, EventSource, UniversalEvent
from .registry import EVENT_TYPES, is_registered, require_registered

__all__ = [
    "EVENT_TYPES",
    "EventScope",
    "EventSeverity",
    "EventSource",
    "UniversalEvent",
    "is_registered",
    "require_registered",
]
