#!/usr/bin/env python3
"""Per-instance telemetry for the Linux Agent.

CPU/RSS are collected from the instance process (systemd MainPID), not from the
Agent host. Network counters are reported only when the runtime declares a
network interface dedicated to the instance; the collector deliberately does
not pretend host-wide traffic is instance traffic.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

import instance_runtime

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
SAMPLE_STATE_DIR = STATE_DIR / "instance-telemetry"


def _systemd_main_pid(instance_id: str) -> int | None:
    unit = f"capivara-instance-{instance_id}.service"
    try:
        result = subprocess.run(
            ["systemctl", "show", unit, "--property=MainPID", "--value", "--no-pager"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        value = int((result.stdout or "0").strip())
        return value if result.returncode == 0 and value > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _proc_stat(pid: int) -> tuple[int, int] | None:
    try:
        parts = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        return int(parts[13]) + int(parts[14]), int(parts[21])
    except (OSError, ValueError, IndexError):
        return None


def _rss_bytes(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _host_uptime() -> float | None:
    try:
        return float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _cpu_percent(instance_id: str, process_ticks: int) -> float | None:
    now = time.monotonic(); path = SAMPLE_STATE_DIR / f"{instance_id}.json"
    previous = None
    try: previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError): pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"monotonic": now, "ticks": process_ticks}), encoding="utf-8")
    os.chmod(temp, 0o600); os.replace(temp, path)
    if not isinstance(previous, dict): return None
    try:
        elapsed = now - float(previous["monotonic"]); delta = process_ticks - int(previous["ticks"])
        if elapsed <= 0 or delta < 0: return None
        hz = int(os.sysconf("SC_CLK_TCK"))
        return round((delta / hz) / elapsed * 100.0, 2)
    except (KeyError, TypeError, ValueError, OSError):
        return None


def _network(interface: str | None) -> tuple[int | None, int | None]:
    interface = str(interface or "").strip()
    if not interface or "/" in interface or ".." in interface: return None, None
    base = Path("/sys/class/net") / interface / "statistics"
    try: rx = int((base / "rx_bytes").read_text().strip()); tx = int((base / "tx_bytes").read_text().strip()); return rx, tx
    except (OSError, ValueError): return None, None


def _storage_used(path_value: Any, *, max_entries: int = 200000) -> int | None:
    root = Path(str(path_value or "")).resolve()
    if not root.is_dir(): return None
    total = 0; seen = 0
    try:
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(current) / name).is_symlink()]
            for name in files:
                seen += 1
                if seen > max_entries: return total
                path = Path(current) / name
                try:
                    if not path.is_symlink(): total += path.stat().st_size
                except OSError: continue
    except OSError: return None
    return total


def _game_query(config: dict[str, Any]) -> dict[str, Any]:
    argv = config.get("query_argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv): return {}
    executable = str(argv[0])
    if not executable.startswith("/"): return {}
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=max(1, min(int(config.get("query_timeout_seconds") or 5), 15)))
        if result.returncode != 0: return {}
        value = json.loads(result.stdout or "{}")
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, subprocess.SubprocessError): return {}


def collect_instance_telemetry(config: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for summary in instance_runtime.list_instances(config):
        instance_id = str(summary.get("instance_id") or "").strip()
        if not instance_id: continue
        record = instance_runtime.get_instance(instance_id) or {}
        adapter = str(record.get("adapter") or "").strip().lower()
        pid = _systemd_main_pid(instance_id) if adapter == "systemd" else None
        cpu = memory = uptime = None
        if pid:
            stat = _proc_stat(pid)
            if stat:
                ticks, started = stat; cpu = _cpu_percent(instance_id, ticks)
                host_uptime = _host_uptime()
                if host_uptime is not None:
                    try: uptime = max(0, int(host_uptime - (started / int(os.sysconf("SC_CLK_TCK")))))
                    except (ValueError, OSError, ZeroDivisionError): uptime = None
            memory = _rss_bytes(pid)
        telemetry_config = record.get("telemetry") if isinstance(record.get("telemetry"), dict) else {}
        rx, tx = _network(telemetry_config.get("network_interface"))
        game = _game_query(telemetry_config)
        try:
            view = instance_runtime.status(config, instance_id)
            state = str(view.get("observed_state") or "unknown").lower()
            health = "healthy" if state == "running" else ("degraded" if state in {"starting", "failed", "unavailable"} else "unknown")
        except Exception:
            health = "unknown"
        results.append({
            "instance_id": instance_id,
            "cpu_percent": cpu,
            "memory_bytes": memory,
            "storage_used_bytes": _storage_used(record.get("path")),
            "network_rx_bytes": rx,
            "network_tx_bytes": tx,
            "players_online": game.get("players_online"),
            "players_max": game.get("players_max"),
            "latency_ms": game.get("latency_ms"),
            "uptime_seconds": uptime,
            "health": str(game.get("health") or health),
        })
    return results


__all__ = ["collect_instance_telemetry"]
