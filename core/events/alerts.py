from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping

from .models import UniversalEvent


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class AlertCandidate:
    """Policy input produced from one domain event.

    Event severity is descriptive metadata about the event itself. Alert severity
    is an independent operational policy decision and is therefore modeled
    separately.
    """

    rule_id: str
    level: AlertSeverity
    message: str
    event_id: str
    event_type: str
    scope: dict[str, str]
    correlation_id: str | None


AlertMessageFactory = Callable[[UniversalEvent], str]


@dataclass(frozen=True)
class AlertRule:
    event_type: str
    rule_id: str
    level: AlertSeverity
    message: str | AlertMessageFactory

    def evaluate(self, event: UniversalEvent) -> AlertCandidate | None:
        if event.type != self.event_type:
            return None
        message = self.message(event) if callable(self.message) else self.message
        return AlertCandidate(
            rule_id=self.rule_id,
            level=self.level,
            message=message,
            event_id=event.id,
            event_type=event.type,
            scope=event.scope.to_dict(),
            correlation_id=event.correlation_id,
        )


DEFAULT_ALERT_RULES: tuple[AlertRule, ...] = (
    AlertRule(
        event_type="AGENT_UPDATE_FAILED",
        rule_id="agent.update.failed",
        level=AlertSeverity.WARNING,
        message="Falha na atualização do Agent.",
    ),
    AlertRule(
        event_type="INSTANCE_INSTALL_FAILED",
        rule_id="instance.install.failed",
        level=AlertSeverity.CRITICAL,
        message="Falha na instalação da instância.",
    ),
    AlertRule(
        event_type="BACKUP_FAILED",
        rule_id="backup.failed",
        level=AlertSeverity.WARNING,
        message="Falha na criação do backup.",
    ),
    AlertRule(
        event_type="INFRASTRUCTURE_UNAVAILABLE",
        rule_id="infrastructure.unavailable",
        level=AlertSeverity.CRITICAL,
        message="Infraestrutura indisponível.",
    ),
    AlertRule(
        event_type="PORT_RANGE_EXHAUSTED",
        rule_id="network.port_range_exhausted",
        level=AlertSeverity.CRITICAL,
        message="Faixa de portas do Agent esgotada.",
    ),
    AlertRule(
        event_type="STEAM_AUTH_REQUIRED",
        rule_id="steam.auth.required",
        level=AlertSeverity.WARNING,
        message="Autenticação Steam necessária.",
    ),
)


class AlertConsumer:
    """Converts selected universal events into alert-policy candidates."""

    def __init__(self, rules: tuple[AlertRule, ...] = DEFAULT_ALERT_RULES) -> None:
        self._rules = tuple(rules)

    def consume(self, event: UniversalEvent) -> list[AlertCandidate]:
        candidates: list[AlertCandidate] = []
        for rule in self._rules:
            candidate = rule.evaluate(event)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    def rules_by_event_type(self) -> Mapping[str, tuple[AlertRule, ...]]:
        grouped: dict[str, list[AlertRule]] = {}
        for rule in self._rules:
            grouped.setdefault(rule.event_type, []).append(rule)
        return {key: tuple(value) for key, value in grouped.items()}


__all__ = [
    "AlertCandidate",
    "AlertConsumer",
    "AlertRule",
    "AlertSeverity",
    "DEFAULT_ALERT_RULES",
]
