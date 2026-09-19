#!/usr/bin/env python3
"""Administrative YARA-X security read model."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from universal_event_repository import UniversalEventRepository


def _require_admin(user: dict[str, Any] | None) -> dict[str, Any]:
    actor = user if isinstance(user, dict) else {}
    if str(actor.get("role") or "").strip().lower() not in {"admin", "controller"}:
        raise PermissionError("administrator access required")
    return actor


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8")
        except Exception:
            return {}
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _safe_scan_match(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    def text(key: str, limit: int) -> str | None:
        raw = str(value.get(key) or "").replace("\x00", " ").replace("\r", " ").replace("\n", " ").strip()
        return raw[:limit] or None
    tags = [
        str(item).strip().lower()[:64]
        for item in (value.get("tags") or [])
        if str(item).strip()
    ][:20]
    relative_path = text("relative_path", 1024)
    if relative_path and (relative_path.startswith("/") or relative_path.startswith("../") or "/../" in relative_path):
        relative_path = None
    return {
        "rule": text("rule", 191) or "unknown",
        "tags": tags,
        "file_name": text("file_name", 255),
        "relative_path": relative_path,
        "detection_name": text("detection_name", 500),
        "threat_name": text("threat_name", 191),
        "malware_family": text("malware_family", 191),
        "category": text("category", 128),
        "description": text("description", 500),
    }


def _agent_security_rows(backend) -> list[dict[str, Any]]:
    with backend.connect() as connection:
        rows = connection.execute(
            "SELECT a.id AS agent_id,a.name,a.status,"
            "ari.health_status,ari.capivara_version,ari.last_seen,ari.capabilities_json "
            "FROM agents a LEFT JOIN agent_runtime_inventory ari ON ari.agent_id=a.id "
            "ORDER BY a.name,a.id"
        ).fetchall()
    result: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        capabilities = _json_object(row.get("capabilities_json"))
        security = capabilities.get("content_security")
        security = dict(security) if isinstance(security, dict) else {}
        result.append(
            {
                "agent_id": row.get("agent_id"),
                "name": row.get("name"),
                "agent_status": row.get("status"),
                "health_status": row.get("health_status") or "offline",
                "capivara_version": row.get("capivara_version"),
                "last_seen": row.get("last_seen"),
                "ready": bool(security.get("ready")),
                "state": security.get("state") or "unknown",
                "engine_version": security.get("engine_version"),
                "engine_pinned_version": security.get("engine_pinned_version"),
                "engine_managed": security.get("engine_managed"),
                "ruleset_version": security.get("ruleset_version"),
                "ruleset_pinned_version": security.get("ruleset_pinned_version"),
                "rules_count": int(security.get("rules_count") or 0),
                "ruleset_checksum_valid": security.get("ruleset_checksum_valid"),
                "rules_managed": security.get("rules_managed"),
                "last_error": str(security.get("last_error") or "")[:1000] or None,
            }
        )
    return result


def _scan_events(backend, *, agent_id: str | None, instance_id: str | None, limit: int) -> list[dict[str, Any]]:
    repo = UniversalEventRepository(backend)
    repo.initialize()
    events = repo.list_events(
        limit=max(50, min(int(limit) * 4, 1000)),
        agent_id=agent_id,
        instance_id=instance_id,
    )
    safe: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event_type") or "").upper()
        if event_type not in {"YARAX_SCAN_STARTED", "YARAX_SCAN_COMPLETED", "YARAX_SCAN_FAILED"}:
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        raw_matches = data.get("matches") if isinstance(data.get("matches"), list) else []
        matches = [match for match in (_safe_scan_match(item) for item in raw_matches[:200]) if match is not None]
        matched_files = sorted({
            str(match.get("relative_path") or match.get("file_name") or "").strip()
            for match in matches
            if str(match.get("relative_path") or match.get("file_name") or "").strip()
        })[:50]
        safe.append(
            {
                "event_id": event.get("event_id"),
                "event_type": event_type,
                "occurred_at": event.get("occurred_at"),
                "severity": event.get("severity"),
                "agent_id": event.get("agent_id"),
                "instance_id": event.get("instance_id"),
                "correlation_id": event.get("correlation_id"),
                "content_id": data.get("content_id"),
                "provider": data.get("provider"),
                "game_id": data.get("game_id"),
                "result": data.get("result"),
                "duration_ms": data.get("duration_ms"),
                "target_kind": data.get("target_kind"),
                "engine_version": data.get("engine_version"),
                "ruleset_version": data.get("ruleset_version"),
                "match_count": min(len(matches), 200),
                "matched_files": matched_files,
                "matches": matches[:20],
                "error": str(data.get("error") or "")[:1000] or None,
            }
        )
        if len(safe) >= limit:
            break
    return safe


def yarax_security_overview(*, user, backend, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    _require_admin(user)
    values = filters if isinstance(filters, dict) else {}
    agent_id = str(values.get("agent_id") or "").strip() or None
    instance_id = str(values.get("instance_id") or "").strip() or None
    result_filter = str(values.get("result") or "").strip().lower() or None
    try:
        limit = max(1, min(int(values.get("limit") or 200), 500))
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc

    agents = _agent_security_rows(backend)
    if agent_id:
        agents = [row for row in agents if str(row.get("agent_id") or "") == agent_id]

    events = _scan_events(backend, agent_id=agent_id, instance_id=instance_id, limit=limit)
    if result_filter:
        events = [row for row in events if str(row.get("result") or "").lower() == result_filter]

    states = Counter(str(row.get("state") or "unknown").lower() for row in agents)
    results = Counter(str(row.get("result") or "started").lower() for row in events)
    return {
        "schema_version": 1,
        "kind": "CapivaraYaraXSecurityOverview",
        "filters": {
            "agent_id": agent_id,
            "instance_id": instance_id,
            "result": result_filter,
            "limit": limit,
        },
        "summary": {
            "agents_total": len(agents),
            "agents_ready": sum(1 for row in agents if row.get("ready")),
            "agents_not_ready": sum(1 for row in agents if not row.get("ready")),
            "states": dict(sorted(states.items())),
            "recent_scans": len(events),
            "results": dict(sorted(results.items())),
        },
        "agents": agents,
        "events": events,
    }


__all__ = ["yarax_security_overview"]
