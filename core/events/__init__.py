"""Universal Event Platform public contract.

Producers should depend on this package instead of dashboard, alert, timeline,
or storage implementations.
"""

from .alerts import AlertCandidate, AlertConsumer, AlertRule, AlertSeverity
from .automation import AutomationEngine, AutomationRule
from .context import EventContext
from .models import EventScope, EventSeverity, EventSource, UniversalEvent
from .observability import EventPlatformMetrics, EventPlatformSnapshot, ObservedEventSink
from .publisher import EventPublisher, publish
from .registry import EVENT_TYPES, is_registered, require_registered
from .retention import EventRetentionPolicy, EventRetentionService, RetentionResult
from .storage import EventStore
from .streaming import CompositeEventSink, EventStreamHub, Subscription
from .timeline import TimelineConsumer, TimelineEntry, TimelineEventSource
from .validator import EventValidationError, validate_event

__all__ = [
    "EVENT_TYPES",
    "AlertCandidate",
    "AlertConsumer",
    "AlertRule",
    "AlertSeverity",
    "AutomationEngine",
    "AutomationRule",
    "CompositeEventSink",
    "EventContext",
    "EventPlatformMetrics",
    "EventPlatformSnapshot",
    "EventPublisher",
    "EventRetentionPolicy",
    "EventRetentionService",
    "EventScope",
    "EventSeverity",
    "EventSource",
    "EventStore",
    "EventStreamHub",
    "EventValidationError",
    "ObservedEventSink",
    "RetentionResult",
    "Subscription",
    "TimelineConsumer",
    "TimelineEntry",
    "TimelineEventSource",
    "UniversalEvent",
    "is_registered",
    "publish",
    "require_registered",
    "validate_event",
]
