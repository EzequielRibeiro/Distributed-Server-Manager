"""Read-only bounded recovery evidence collection for an Agent heartbeat.

Caller must pass instance IDs from the Agent's own trusted registry. This
function does not mutate any journal or verify runtime health.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Callable

from minecraft_serverpack_recovery_observation import recovery_observation
from minecraft_recovery_loader_proof import verify_recovered_loader


def collect_recovery_observations(
    instance_ids: list[str], *, agent_id: str,
    read_operation: Callable[[str], dict[str, Any] | None],
    read_instance: Callable[[str], dict[str, Any] | None] | None = None,
    observed_at: str | None = None,
    limit: int = 128,
) -> list[dict[str, Any]]:
    if not agent_id or not 1 <= limit <= 128:
        return []
    timestamp = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    observations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for instance_id in instance_ids:
        if not isinstance(instance_id, str) or not instance_id or instance_id in seen:
            continue
        seen.add(instance_id)
        if len(observations) >= limit:
            break
        try:
            record = read_operation(instance_id)
        except (OSError, ValueError):
            continue
        claim = recovery_observation(record, instance_id=instance_id,
                                     agent_id=agent_id, observed_at=timestamp)
        if claim is not None:
            if read_instance is not None:
                try:
                    proof = verify_recovered_loader(read_instance(instance_id), record,
                        instance_id=instance_id, agent_id=agent_id)
                except (OSError, ValueError):
                    proof = None
                if proof:
                    claim["loader_proof"] = proof
            observations.append(claim)
    return observations
