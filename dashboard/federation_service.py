"""Multi-datacenter federation primitives for the Capivara control plane.

E1 keeps the existing Controller -> Agent authority model intact while adding a
read-mostly global inventory of peer controllers.  A datacenter remains locally
authoritative for its agents and instances; federation never reassigns local
resources implicitly.
"""
from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class FederationPeer:
    peer_id: str
    name: str
    endpoint: str
    region_id: Optional[str]
    datacenter_id: Optional[str]
    status: str
    last_seen_at: Optional[str]


class FederationService:
    """Persistence-neutral federation orchestration.

    The supplied repository owns SQL/backend details.  Keeping policy here makes
    federation usable by SQLite, PostgreSQL and MySQL/MariaDB without teaching
    the placement engine about database-specific behaviour.
    """

    def __init__(self, repository: Any, *, stale_after_seconds: int = 90):
        self.repository = repository
        self.stale_after_seconds = max(15, int(stale_after_seconds))

    def register_peer(
        self,
        *,
        name: str,
        endpoint: str,
        region_id: Optional[str] = None,
        datacenter_id: Optional[str] = None,
        peer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not name.strip():
            raise ValueError("federation peer name is required")
        endpoint = endpoint.strip().rstrip("/")
        if not endpoint.startswith("https://"):
            raise ValueError("federation peer endpoint must use https")
        peer_id = peer_id or f"fed-{secrets.token_hex(8)}"
        record = {
            "peer_id": peer_id,
            "name": name.strip(),
            "endpoint": endpoint,
            "region_id": region_id,
            "datacenter_id": datacenter_id,
            "status": "pending",
            "last_seen_at": None,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        self.repository.upsert_peer(record)
        return record

    def record_heartbeat(self, peer_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(snapshot, dict):
            raise ValueError("federation snapshot must be an object")
        safe = self._validate_snapshot(peer_id, snapshot)
        observed_at = utcnow()
        self.repository.record_snapshot(peer_id, safe, observed_at=observed_at)
        self.repository.mark_peer_seen(peer_id, observed_at=observed_at)
        return {"peer_id": peer_id, "status": "online", "observed_at": observed_at}

    def global_inventory(self) -> Dict[str, Any]:
        peers = list(self.repository.list_peers())
        snapshots = list(self.repository.latest_snapshots())
        return {
            "generated_at": utcnow(),
            "peer_count": len(peers),
            "peers": peers,
            "datacenters": snapshots,
            "capacity": self._aggregate_capacity(snapshots),
        }

    @staticmethod
    def _aggregate_capacity(snapshots: Iterable[Dict[str, Any]]) -> Dict[str, float]:
        totals = {"agents": 0.0, "instances": 0.0, "cpu_capacity": 0.0, "memory_bytes": 0.0, "disk_bytes": 0.0}
        for snapshot in snapshots:
            capacity = snapshot.get("capacity") or {}
            for key in totals:
                try:
                    totals[key] += float(capacity.get(key, 0) or 0)
                except (TypeError, ValueError):
                    continue
        return totals

    @staticmethod
    def _validate_snapshot(peer_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        claimed = str(snapshot.get("peer_id") or peer_id)
        if claimed != peer_id:
            raise ValueError("federation peer identity mismatch")
        capacity = snapshot.get("capacity") or {}
        if not isinstance(capacity, dict):
            raise ValueError("federation capacity must be an object")
        # Never accept credentials, arbitrary commands or executable payloads as
        # federation inventory.  E1 exchanges topology/capacity metadata only.
        forbidden = {"authorization", "token", "secret", "password", "command", "shell", "script"}
        lowered = {str(key).lower() for key in snapshot}
        if lowered & forbidden:
            raise ValueError("unsafe field in federation snapshot")
        return json.loads(json.dumps(snapshot, separators=(",", ":"), sort_keys=True))
