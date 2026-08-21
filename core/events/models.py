from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4


class EventSeverity(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class EventSource:
    type: str
    id: str

    def __post_init__(self) -> None:
        if not self.type.strip():
            raise ValueError("event source type must not be empty")
        if not self.id.strip():
            raise ValueError("event source id must not be empty")


@dataclass(frozen=True)
class EventScope:
    controller_id: Optional[str] = None
    agent_id: Optional[str] = None
    customer_id: Optional[str] = None
    instance_id: Optional[str] = None

    def to_dict(self) -> Dict[str, str]:
        return {
            key: value
            for key, value in {
                "controller_id": self.controller_id,
                "agent_id": self.agent_id,
                "customer_id": self.customer_id,
                "instance_id": self.instance_id,
            }.items()
            if value is not None
        }


@dataclass(frozen=True)
class UniversalEvent:
    type: str
    source: EventSource
    severity: EventSeverity = EventSeverity.INFO
    data: Dict[str, Any] = field(default_factory=dict)
    scope: EventScope = field(default_factory=EventScope)
    version: int = 1
    id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.type or self.type != self.type.upper():
            raise ValueError("event type must be a non-empty uppercase identifier")
        if self.version < 1:
            raise ValueError("event version must be >= 1")
        if self.timestamp.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "version": self.version,
            "timestamp": self.timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "severity": self.severity.value,
            "source": {
                "type": self.source.type,
                "id": self.source.id,
            },
            "scope": self.scope.to_dict(),
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "data": dict(self.data),
        }
