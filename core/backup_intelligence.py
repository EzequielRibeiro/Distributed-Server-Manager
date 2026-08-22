#!/usr/bin/env python3
"""Operational intelligence for Capivara Universal Smart Backup."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

PRESETS: dict[str, dict[str, Any]] = {
    "balanced": {
        "enabled": True,
        "mode": "full",
        "consistency": "live",
        "compression": "gzip",
        "interval_seconds": 21600,
        "retention_count": 14,
        "include_paths": [],
        "exclude_paths": [],
        "description": "Backup completo a cada 6 horas, equilibrando proteção e uso de disco.",
    },
    "frequent": {
        "enabled": True,
        "mode": "full",
        "consistency": "live",
        "compression": "gzip",
        "interval_seconds": 3600,
        "retention_count": 48,
        "include_paths": [],
        "exclude_paths": [],
        "description": "Backup completo a cada hora para instâncias com alto valor operacional.",
    },
    "daily": {
        "enabled": True,
        "mode": "full",
        "consistency": "live",
        "compression": "gzip",
        "interval_seconds": 86400,
        "retention_count": 14,
        "include_paths": [],
        "exclude_paths": [],
        "description": "Backup completo diário com retenção de duas semanas.",
    },
    "config-safe": {
        "enabled": True,
        "mode": "config",
        "consistency": "live",
        "compression": "gzip",
        "interval_seconds": 21600,
        "retention_count": 30,
        "include_paths": [],
        "exclude_paths": [],
        "description": "Proteção frequente de configuração com retenção ampliada.",
    },
}


def preset_names() -> list[str]:
    return sorted(PRESETS)


def preset(name: str) -> dict[str, Any]:
    key = str(name or "").strip().lower()
    if key not in PRESETS:
        raise ValueError(f"unknown backup preset: {name}")
    return dict(PRESETS[key])


def apply_preset(instance_id: str, name: str) -> dict[str, Any]:
    item = preset(name)
    item.pop("description", None)
    item["instance_id"] = str(instance_id or "").strip()
    return item


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def evaluate_policy(
    policy: Mapping[str, Any],
    jobs: Iterable[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)

    rows = [dict(row) for row in jobs]
    creates = [row for row in rows if str(row.get("action") or "") == "create"]
    completed = [row for row in creates if str(row.get("status") or "") == "completed"]
    failed = [row for row in creates if str(row.get("status") or "") == "failed"]
    active = [row for row in creates if str(row.get("status") or "") in {"pending", "running"}]

    def event_time(row: Mapping[str, Any]) -> datetime | None:
        return _parse_time(row.get("completed_at") or row.get("updated_at") or row.get("created_at"))

    completed.sort(key=lambda row: event_time(row) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    creates.sort(key=lambda row: event_time(row) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    last_success = completed[0] if completed else None
    last_success_at = event_time(last_success) if last_success else None
    interval = max(300, int(policy.get("interval_seconds") or 21600))
    next_due = None if last_success_at is None else last_success_at.timestamp() + interval
    seconds_until_due = None if next_due is None else int(next_due - current.timestamp())

    consecutive_failures = 0
    for row in creates:
        status = str(row.get("status") or "")
        if status == "failed":
            consecutive_failures += 1
            continue
        if status == "completed":
            break

    terminal = [row for row in creates[:20] if str(row.get("status") or "") in {"completed", "failed"}]
    terminal_success = sum(1 for row in terminal if str(row.get("status")) == "completed")
    success_rate = round((terminal_success / len(terminal)) * 100.0, 1) if terminal else None

    enabled = bool(policy.get("enabled"))
    if not enabled:
        health = "disabled"
        recommendation = "Ative a política para retomar a proteção automática."
    elif consecutive_failures >= 2:
        health = "degraded"
        recommendation = "Investigue as falhas recentes antes da próxima janela de backup."
    elif last_success_at is None:
        created_at = _parse_time(policy.get("created_at"))
        if created_at and (current - created_at).total_seconds() >= interval:
            health = "overdue"
            recommendation = "Nenhum backup concluído dentro do intervalo esperado; solicite ou investigue a execução."
        else:
            health = "never_run"
            recommendation = "A política ainda não possui backup concluído."
    elif seconds_until_due is not None and seconds_until_due < -interval:
        health = "overdue"
        recommendation = "O backup está atrasado além de uma janela completa; verifique Agent e fila de jobs."
    elif seconds_until_due is not None and seconds_until_due <= 0:
        health = "due"
        recommendation = "Backup vencido e elegível para execução automática."
    else:
        health = "healthy"
        recommendation = "Política dentro da janela esperada."

    last_error = None
    for row in creates:
        if str(row.get("status") or "") == "failed":
            last_error = row.get("last_error")
            break

    return {
        "schema_version": 1,
        "kind": "CapivaraBackupHealth",
        "instance_id": policy.get("instance_id"),
        "agent_id": policy.get("agent_id"),
        "policy_id": policy.get("policy_id"),
        "policy_revision": policy.get("revision"),
        "enabled": enabled,
        "health": health,
        "interval_seconds": interval,
        "last_success_at": _iso(last_success_at),
        "last_backup_id": last_success.get("backup_id") if last_success else None,
        "last_size_bytes": last_success.get("size_bytes") if last_success else None,
        "last_sha256": last_success.get("sha256") if last_success else None,
        "next_due_at": _iso(datetime.fromtimestamp(next_due, timezone.utc)) if next_due is not None else None,
        "seconds_until_due": seconds_until_due,
        "pending_or_running": len(active),
        "consecutive_failures": consecutive_failures,
        "success_rate_percent": success_rate,
        "last_error": last_error,
        "recommendation": recommendation,
    }


def aggregate_health(items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(item) for item in items]
    counts: dict[str, int] = {}
    for row in rows:
        state = str(row.get("health") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    attention = sum(counts.get(state, 0) for state in ("degraded", "overdue"))
    return {
        "schema_version": 1,
        "kind": "CapivaraBackupFleetHealth",
        "count": len(rows),
        "attention_required": attention,
        "counts": counts,
        "policies": rows,
    }


__all__ = [
    "PRESETS",
    "aggregate_health",
    "apply_preset",
    "evaluate_policy",
    "preset",
    "preset_names",
]
