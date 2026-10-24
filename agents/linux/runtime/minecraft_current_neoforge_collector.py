"""Bounded current NeoForge heartbeat observations, independent of migration recovery."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from minecraft_current_neoforge_attestation import attest_current_neoforge


def collect_current_neoforge_attestations(
    instance_ids: list[str], *, agent_id: str,
    read_instance: Callable[[str], dict[str, Any] | None],
    observed_at: str | None = None, limit: int = 128,
) -> list[dict[str, Any]]:
    if not agent_id or not 1 <= limit <= 128:
        return []
    timestamp = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for instance_id in instance_ids:
        if not isinstance(instance_id, str) or instance_id in seen or not instance_id:
            continue
        seen.add(instance_id)
        if len(results) >= limit:
            break
        try:
            record = read_instance(instance_id)
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict) or record.get("runtime_id") != "minecraft.java.neoforge":
            continue
        # Derive the expected build from Agent-owned installation metadata, not
        # from a caller-supplied version or filesystem scan.
        source = record.get("content_root")
        if not isinstance(source, str) or not source:
            source = (record.get("installation") or {}).get("content_root") if isinstance(record.get("installation"), dict) else None
        if not isinstance(source, str) or not source:
            continue
        path = Path(source)
        if not path.is_absolute() or path.parts[-3:-2] != ("neoforge",):
            continue
        version = path.name
        claim = attest_current_neoforge(record, instance_id=instance_id,
                                        agent_id=agent_id, expected_version=version)
        if claim:
            claim["observed_at"] = timestamp
            results.append(claim)
    return results
