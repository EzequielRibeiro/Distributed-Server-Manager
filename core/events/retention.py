from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol


class RetentionEventStore(Protocol):
    def count_before(self, cutoff: datetime) -> int: ...

    def delete_before(self, cutoff: datetime) -> int: ...


@dataclass(frozen=True)
class EventRetentionPolicy:
    max_age_days: int = 90

    def __post_init__(self) -> None:
        if self.max_age_days < 1:
            raise ValueError("max_age_days must be >= 1")

    def cutoff(self, now: datetime | None = None) -> datetime:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("retention clock must be timezone-aware")
        return current.astimezone(timezone.utc) - timedelta(days=self.max_age_days)


@dataclass(frozen=True)
class RetentionResult:
    cutoff: datetime
    matched: int
    deleted: int
    dry_run: bool


class EventRetentionService:
    """Applies bounded cleanup only to Universal Event Platform rows."""

    def __init__(self, store: RetentionEventStore, policy: EventRetentionPolicy) -> None:
        self._store = store
        self._policy = policy

    def run(self, *, now: datetime | None = None, dry_run: bool = True) -> RetentionResult:
        cutoff = self._policy.cutoff(now)
        matched = self._store.count_before(cutoff)
        deleted = 0 if dry_run else self._store.delete_before(cutoff)
        return RetentionResult(
            cutoff=cutoff,
            matched=matched,
            deleted=deleted,
            dry_run=dry_run,
        )


__all__ = [
    "EventRetentionPolicy",
    "EventRetentionService",
    "RetentionEventStore",
    "RetentionResult",
]
