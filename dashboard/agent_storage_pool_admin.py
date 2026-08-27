#!/usr/bin/env python3
"""Controller-side desired-state administration for Agent Storage Pools."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from configuration_repository import ConfigurationRepository

NAMESPACE = "capivara.agent.storage"
DEFAULT_ROOT = "/var/lib/capivara-instances"
_TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_FORBIDDEN_ROOTS = tuple(Path(value) for value in ("/boot", "/dev", "/etc", "/proc", "/root", "/run", "/sys", "/usr"))


def _json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict): return dict(value)
    if isinstance(value, (bytes, bytearray)):
        try: value = value.decode("utf-8")
        except Exception: return {}
    try: parsed = json.loads(str(value)) if value else {}
    except (TypeError, ValueError): return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _token(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text): raise ValueError(f"invalid {label}")
    return text


def _root(value: Any) -> str:
    raw = str(value or "").strip(); path = Path(raw)
    if not raw or not path.is_absolute(): raise ValueError("root_path must be absolute")
    resolved = path.resolve(strict=False)
    if resolved == Path("/"): raise ValueError("root_path cannot be filesystem root")
    for forbidden in _FORBIDDEN_ROOTS:
        try: resolved.relative_to(forbidden)
        except ValueError: continue
        raise ValueError("root_path is inside a protected system path")
    return str(resolved)


def _pool(raw: dict[str, Any]) -> dict[str, Any]:
    pool_id = _token(raw.get("id") or raw.get("storage_pool_id"), "storage_pool_id")
    storage_class = _token(str(raw.get("storage_class") or "standard").lower(), "storage_class")
    reserve = int(raw.get("reserve_bytes") or 0); priority = int(raw.get("priority") or 0)
    if reserve < 0: raise ValueError("reserve_bytes cannot be negative")
    return {"id": pool_id, "name": str(raw.get("name") or pool_id).strip()[:160] or pool_id,
            "root_path": _root(raw.get("root_path")), "storage_class": storage_class,
            "enabled": bool(raw.get("enabled", True)), "priority": priority, "reserve_bytes": reserve}


class AgentStoragePoolAdmin:
    def __init__(self, backend):
        self.backend = backend; self.dialect = dialect_for_backend(backend); self.config = ConfigurationRepository(backend)

    def initialize(self): return self.backend.initialize()

    def _agent(self, agent_id: str) -> dict[str, Any]:
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try: row = session.execute(f"SELECT id,metadata_json FROM agents WHERE id={ph}", (agent_id,)).fetchone()
            finally: session.close()
        if row is None: raise LookupError(agent_id)
        return dict(row)

    def _telemetry_pools(self, agent: dict[str, Any]) -> list[dict[str, Any]]:
        metadata = _json(agent.get("metadata_json")); telemetry = metadata.get("telemetry") if isinstance(metadata.get("telemetry"), dict) else {}
        return [dict(item) for item in telemetry.get("storage_pools") or [] if isinstance(item, dict)]

    def _desired(self, agent_id: str) -> dict[str, Any]:
        configured = self.config.get(scope_type="agent", scope_id=agent_id, namespace=NAMESPACE)
        value = dict(configured.get("value") or {}) if configured and isinstance(configured.get("value"), dict) else {}
        pools = value.get("storage_pools") if isinstance(value.get("storage_pools"), list) else None
        if not pools:
            agent = self._agent(agent_id); observed = self._telemetry_pools(agent)
            pools = [{k: item.get(k) for k in ("id","name","root_path","storage_class","enabled","priority","reserve_bytes")} for item in observed]
        if not pools:
            pools = [{"id":"default","name":"Default","root_path":str(value.get("instance_storage_root") or DEFAULT_ROOT),"storage_class":"standard","enabled":True,"priority":0,"reserve_bytes":0}]
        normalized = [_pool(dict(item)) for item in pools]
        default_id = str(value.get("default_storage_pool_id") or "").strip()
        if not default_id:
            defaults = [str(item.get("id")) for item in self._telemetry_pools(self._agent(agent_id)) if item.get("default")]
            default_id = defaults[0] if defaults and defaults[0] in {p["id"] for p in normalized} else normalized[0]["id"]
        return {"instance_storage_root": str(value.get("instance_storage_root") or DEFAULT_ROOT),
                "storage_pools": normalized, "default_storage_pool_id": default_id, "migrate_existing": False}

    def detail(self, agent_id: str) -> dict[str, Any]:
        agent_id = str(agent_id or "").strip(); agent = self._agent(agent_id); desired = self._desired(agent_id); observed = self._telemetry_pools(agent)
        observed_by_id = {str(item.get("id")): item for item in observed}
        pools=[]
        for item in desired["storage_pools"]:
            view=dict(item); view["default"] = item["id"] == desired["default_storage_pool_id"]
            if item["id"] in observed_by_id: view["observed"] = observed_by_id[item["id"]]
            pools.append(view)
        return {"agent_id":agent_id,"default_storage_pool_id":desired["default_storage_pool_id"],"pools":pools}

    def _store(self, agent_id: str, desired: dict[str, Any], actor: str):
        return self.config.put({"scope_type":"agent","scope_id":agent_id,"namespace":NAMESPACE,"value":desired}, updated_by=actor)

    def upsert(self, agent_id: str, raw: dict[str, Any], *, actor: str) -> tuple[dict[str, Any], str, bool]:
        desired=self._desired(agent_id); pool=_pool(raw); ids={p["id"] for p in desired["storage_pools"]}; created=pool["id"] not in ids
        roots={p["root_path"]:p["id"] for p in desired["storage_pools"] if p["id"] != pool["id"]}
        if pool["root_path"] in roots: raise ValueError("another Storage Pool already uses this root_path")
        desired["storage_pools"]=[pool if p["id"]==pool["id"] else p for p in desired["storage_pools"]]
        if created: desired["storage_pools"].append(pool)
        if len(desired["storage_pools"])==1: desired["default_storage_pool_id"]=pool["id"]
        self._store(agent_id,desired,actor); return self.detail(agent_id), pool["id"], created

    def set_enabled(self, agent_id: str, pool_id: str, enabled: bool, *, actor: str):
        desired=self._desired(agent_id); pool_id=_token(pool_id,"storage_pool_id"); found=False
        for pool in desired["storage_pools"]:
            if pool["id"]==pool_id: pool["enabled"]=bool(enabled); found=True
        if not found: raise LookupError(pool_id)
        if not enabled and desired["default_storage_pool_id"]==pool_id: raise ValueError("default Storage Pool cannot be disabled")
        self._store(agent_id,desired,actor); return self.detail(agent_id)

    def set_default(self, agent_id: str, pool_id: str, *, actor: str):
        desired=self._desired(agent_id); pool_id=_token(pool_id,"storage_pool_id")
        matches=[p for p in desired["storage_pools"] if p["id"]==pool_id]
        if not matches: raise LookupError(pool_id)
        if not matches[0]["enabled"]: raise ValueError("disabled Storage Pool cannot be default")
        desired["default_storage_pool_id"]=pool_id; self._store(agent_id,desired,actor); return self.detail(agent_id)

    def remove(self, agent_id: str, pool_id: str, *, actor: str):
        desired=self._desired(agent_id); pool_id=_token(pool_id,"storage_pool_id")
        if desired["default_storage_pool_id"]==pool_id: raise ValueError("default Storage Pool cannot be removed")
        agent=self._agent(agent_id); metadata=_json(agent.get("metadata_json")); assigned=[]
        for item in metadata.get("instance_telemetry") or []:
            if isinstance(item,dict) and str(item.get("storage_pool_id") or "")==pool_id: assigned.append(str(item.get("instance_id") or ""))
        if assigned: raise ValueError("Storage Pool still has assigned instances: "+", ".join(assigned[:5]))
        before=len(desired["storage_pools"]); desired["storage_pools"]=[p for p in desired["storage_pools"] if p["id"]!=pool_id]
        if len(desired["storage_pools"])==before: raise LookupError(pool_id)
        if not desired["storage_pools"]: raise ValueError("Agent must retain at least one Storage Pool")
        self._store(agent_id,desired,actor); return self.detail(agent_id)


__all__=["AgentStoragePoolAdmin","NAMESPACE"]
