from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .models import UniversalEvent


AutomationPredicate = Callable[[UniversalEvent], bool]
AutomationAction = Callable[[UniversalEvent], None]


@dataclass(frozen=True)
class AutomationRule:
    id: str
    predicate: AutomationPredicate
    action: AutomationAction
    enabled: bool = True

    @classmethod
    def for_event_type(
        cls,
        rule_id: str,
        event_type: str,
        action: AutomationAction,
        *,
        enabled: bool = True,
    ) -> "AutomationRule":
        return cls(
            id=rule_id,
            predicate=lambda event: event.type == event_type,
            action=action,
            enabled=enabled,
        )


class AutomationEngine:
    """Executes explicitly registered automation hooks for domain events.

    The engine does not execute shell commands or infer actions from payloads.
    All actions must be trusted callables registered by application code.
    """

    def __init__(self, rules: tuple[AutomationRule, ...] = ()) -> None:
        self._rules = list(rules)

    def register(self, rule: AutomationRule) -> None:
        if any(existing.id == rule.id for existing in self._rules):
            raise ValueError(f"duplicate automation rule: {rule.id}")
        self._rules.append(rule)

    def handle(self, event: UniversalEvent) -> tuple[str, ...]:
        matched: list[str] = []
        for rule in tuple(self._rules):
            if not rule.enabled or not rule.predicate(event):
                continue
            rule.action(event)
            matched.append(rule.id)
        return tuple(matched)

    @property
    def rule_count(self) -> int:
        return len(self._rules)


__all__ = ["AutomationAction", "AutomationEngine", "AutomationPredicate", "AutomationRule"]
