#!/usr/bin/env python3
"""Read-only infrastructure views for the administrative Dashboard.

This module deliberately keeps infrastructure observation separate from Customer
instance lifecycle. The Controller dashboard consumes host/Agent telemetry here;
instance actions remain in the Customer administration surface.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_game_data_repository import AgentGameDataRepository
from agent_runtime_repository import AgentRuntimeRepository, AgentRuntimeNotFound
from alert_repository import AlertSession, dialect_for_backend
from observability_repository import ObservabilityRepository

_CPU_SAMPLE: tuple[int, int] | None = None
_PROCESS_SAMPLE: tuple[float, float] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(float(value), 2)))


def _cpu_ticks() -> tuple[int, int] | None:
    try:
        fields = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
        ticks = [int(item) for item in fields]
        return sum(ticks), ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    except (OSError, ValueError, IndexError):
        return None


def _controller_cpu() -> float | None:
    global _CPU_SAMPLE
    current = _cpu_ticks()
    if current is None:
        return None
    previous = _CPU_SAMPLE; _CPU_SAMPLE = current
    if previous is None:
        return None
    total = current[0] - previous[0]; idle = current[1] - previous[1]
    return _clamp((total - idle) * 100.0 / total) if total > 0 else None


def _memory() -> dict[str, Any]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if key in {"MemTotal", "MemAvailable", "MemFree"}:
                values[key] = int(rest.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    total = values.get("MemTotal"); available = values.get("MemAvailable", values.get("MemFree"))
    used = max(0, total - available) if total is not None and available is not None else None
    return {"total_bytes": total, "available_bytes": available, "used_bytes": used,
            "used_percent": _clamp(used * 100.0 / total) if used is not None and total else None}


def _dashboard_process() -> dict[str, Any]:
    global _PROCESS_SAMPLE
    pid = os.getpid(); rss = threads = cpu = None
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        statm = Path(f"/proc/{pid}/statm").read_text(encoding="utf-8").split()
        process_seconds = (int(stat[13]) + int(stat[14])) / float(os.sysconf(os.sysconf_names["SC_CLK_TCK"]))
        rss = int(statm[1]) * int(os.sysconf("SC_PAGE_SIZE"))
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("Threads:"):
                threads = int(line.split()[1]); break
        now = time.monotonic(); previous = _PROCESS_SAMPLE; _PROCESS_SAMPLE = (process_seconds, now)
        if previous and now > previous[1]:
            cores = max(1, int(os.cpu_count() or 1))
            cpu = _clamp((process_seconds - previous[0]) * 100.0 / (now - previous[1]) / cores)
    except (OSError, ValueError, IndexError, KeyError):
        pass
    return {"pid": pid, "cpu_percent": cpu, "rss_bytes": rss, "threads": threads}


def controller_telemetry() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        uptime = None
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        load1 = load5 = load15 = None
    return {
        "collected_at": _now(), "cpu_percent": _controller_cpu(), "logical_cores": os.cpu_count(),
        "memory": _memory(),
        "storage": {"total_bytes": disk.total, "used_bytes": disk.used, "free_bytes": disk.free,
                    "used_percent": _clamp(disk.used * 100.0 / disk.total) if disk.total else None},
        "load": {"load1": load1, "load5": load5, "load15": load15}, "uptime_seconds": uptime,
        "dashboard_process": _dashboard_process(),
    }


def _metric_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("metric_name") or "")
        if name and name not in result:
            result[name] = row
    return result


def _metric_value(metrics: dict[str, dict[str, Any]], name: str) -> Any:
    row = metrics.get(name)
    return row.get("value") if row else None


class AdminInfrastructureService:
    def __init__(self, backend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)
        self.runtime = AgentRuntimeRepository(backend)
        self.observability = ObservabilityRepository(backend)
        self.game_data = AgentGameDataRepository(backend)
        self.backend.initialize(); self.observability.initialize(); self.game_data.initialize()

    def _agent_ids(self, user: dict[str, Any]) -> list[str]:
        role = str(user.get("role") or "")
        scope = str(user.get("scope_id") or "").strip()
        sql = "SELECT id FROM agents"
        params: tuple[Any, ...] = ()
        if role == "controller" and scope:
            sql += f" WHERE controller_id={self.dialect.placeholder}"; params = (scope,)
        sql += " ORDER BY name,id"
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                return [str(row["id"]) for row in session.execute(sql, params).fetchall()]
            finally:
                session.close()

    def _ensure_agent(self, user: dict[str, Any], agent_id: str) -> None:
        if agent_id not in set(self._agent_ids(user)):
            raise PermissionError("Agent is outside the administrative scope")

    def _instance_count(self, agent_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS total FROM instances"; params: tuple[Any, ...] = ()
        if agent_id:
            sql += f" WHERE agent_id={self.dialect.placeholder}"; params = (agent_id,)
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:return int(session.execute(sql, params).fetchone()["total"] or 0)
            finally:session.close()

    def _agent_summary(self, agent_id: str) -> dict[str, Any]:
        try:snapshot = self.runtime.snapshot(agent_id, refresh_health=True)
        except AgentRuntimeNotFound:return {"agent_id": agent_id, "health_status": "offline", "instance_count": self._instance_count(agent_id)}
        metrics = _metric_map(self.observability.latest(agent_id=agent_id, limit=200))
        return {
            "agent_id": agent_id, "node_id": snapshot.get("node_id"), "hostname": snapshot.get("hostname") or snapshot.get("node_name"),
            "os_name": snapshot.get("os_name"), "architecture": snapshot.get("architecture"), "version": snapshot.get("capivara_version"),
            "health_status": snapshot.get("health_status"), "last_seen": snapshot.get("last_seen"), "instance_count": self._instance_count(agent_id),
            "host": {"cpu_percent": _metric_value(metrics,"host.cpu.percent"), "memory_percent": _metric_value(metrics,"host.memory.used.percent"), "storage_percent": _metric_value(metrics,"host.storage.used.percent")},
            "agent": {"cpu_percent": _metric_value(metrics,"agent.cpu.percent"), "memory_bytes": _metric_value(metrics,"agent.memory.rss.bytes")},
        }

    def overview(self, user: dict[str, Any]) -> dict[str, Any]:
        ids = self._agent_ids(user); agents = [self._agent_summary(agent_id) for agent_id in ids]
        counts = {"total": len(agents), "online": 0, "degraded": 0, "offline": 0}
        for agent in agents:
            health = str(agent.get("health_status") or "offline").lower()
            key = "online" if health in {"online","healthy"} else "degraded" if health in {"degraded","transitioning"} else "offline"
            counts[key] += 1
        return {"controller": controller_telemetry(), "agents": agents, "agent_counts": counts,
                "instance_count": sum(int(item.get("instance_count") or 0) for item in agents)}

    def _instances(self, agent_id: str) -> list[dict[str, Any]]:
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    "SELECT i.id,i.name,i.game_id,i.status,i.customer_id,c.name AS customer_name,i.agent_id,a.node_id,ic.contract_id "
                    "FROM instances i LEFT JOIN customers c ON c.id=i.customer_id "
                    "LEFT JOIN agents a ON a.id=i.agent_id LEFT JOIN instance_contracts ic ON ic.instance_id=i.id "
                    f"WHERE i.agent_id={ph} ORDER BY c.name,i.name,i.id", (agent_id,)
                ).fetchall()
            finally:session.close()
        values=[]
        for row in rows:
            item=dict(row); metrics=_metric_map(self.observability.latest(agent_id=agent_id,instance_id=str(row["id"]),limit=100))
            item["telemetry"]={
                "cpu_percent":_metric_value(metrics,"instance.cpu.percent"),
                "memory_bytes":_metric_value(metrics,"instance.memory.bytes"),
                "tasks":_metric_value(metrics,"instance.tasks"),
                "io_read_bytes":_metric_value(metrics,"instance.io.read.bytes"),
                "io_write_bytes":_metric_value(metrics,"instance.io.write.bytes"),
                "pid":_metric_value(metrics,"instance.pid"),
                "health":_metric_value(metrics,"instance.health"),
            };values.append(item)
        return values

    def agent_detail(self, user: dict[str, Any], agent_id: str) -> dict[str, Any]:
        agent_id=str(agent_id or "").strip()
        if not agent_id:raise ValueError("agent_id is required")
        self._ensure_agent(user,agent_id)
        snapshot=self.runtime.snapshot(agent_id,refresh_health=True);metrics=_metric_map(self.observability.latest(agent_id=agent_id,limit=500))
        host={
            "cpu_percent":_metric_value(metrics,"host.cpu.percent"),"memory_percent":_metric_value(metrics,"host.memory.used.percent"),
            "memory_used_bytes":_metric_value(metrics,"host.memory.used.bytes"),"memory_available_bytes":_metric_value(metrics,"host.memory.available.bytes"),
            "storage_percent":_metric_value(metrics,"host.storage.used.percent"),"storage_free_bytes":_metric_value(metrics,"host.storage.free.bytes"),
            "load1":_metric_value(metrics,"host.load.1"),"load5":_metric_value(metrics,"host.load.5"),"load15":_metric_value(metrics,"host.load.15"),
            "uptime_seconds":_metric_value(metrics,"host.uptime.seconds"),"network_rx_bytes":_metric_value(metrics,"host.network.rx.bytes"),"network_tx_bytes":_metric_value(metrics,"host.network.tx.bytes"),
        }
        process={"cpu_percent":_metric_value(metrics,"agent.cpu.percent"),"memory_bytes":_metric_value(metrics,"agent.memory.rss.bytes"),"threads":_metric_value(metrics,"agent.threads"),"pid":_metric_value(metrics,"agent.pid")}
        with self.backend.connect() as connection:
            session=AlertSession(self.backend,connection)
            try:
                row=session.execute(f"SELECT metadata_json FROM agents WHERE id={self.dialect.placeholder}",(agent_id,)).fetchone()
            finally:session.close()
        metadata={}
        if row:
            try:metadata=json.loads(str(row["metadata_json"] or "{}"))
            except (ValueError,TypeError):metadata={}
        jobs=self.game_data.list_for_agent(agent_id)
        installed:dict[str,dict[str,Any]]={}
        for job in jobs:
            env=str(job.get("environment_id") or "")
            if env and env not in installed and str(job.get("status") or "").lower()=="completed" and str(job.get("action") or "install").lower()=="install":installed[env]=job
        return {"agent":snapshot,"host_telemetry":host,"agent_telemetry":process,"instances":self._instances(agent_id),
                "game_data":{"installed":list(installed.values()),"jobs":jobs[:50]},"recent_logs":metadata.get("recent_logs") or [],
                "metrics_collected":len(metrics)}


__all__=["AdminInfrastructureService","controller_telemetry"]
