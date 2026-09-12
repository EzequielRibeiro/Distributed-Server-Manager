#!/usr/bin/env python3
"""Per-instance telemetry for the Linux Agent.

CPU and memory are collected from the complete systemd cgroup when available,
so wrapper processes do not hide resource usage from child game processes.
MainPID /proc sampling remains a compatibility fallback. Systemd IP accounting
is collected from the unit, and DayZ query telemetry uses its reserved Steam
query port directly through A2S_INFO without an external helper process.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import time
from typing import Any

import instance_runtime

STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
SAMPLE_STATE_DIR = STATE_DIR / "instance-telemetry"
CGROUP_ROOT = Path(os.environ.get("CAPIVARA_CGROUP_ROOT", "/sys/fs/cgroup"))
_A2S_INFO_REQUEST = b"\xff\xff\xff\xffTSource Engine Query\x00"
_A2S_HEADER = b"\xff\xff\xff\xff"


def _systemd_main_pid(instance_id: str) -> int | None:
    unit = f"capivara-instance-{instance_id}.service"
    try:
        result = subprocess.run(
            ["systemctl", "show", unit, "--property=MainPID", "--value", "--no-pager"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        value = int((result.stdout or "0").strip())
        return value if result.returncode == 0 and value > 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _systemd_cgroup(instance_id: str) -> str | None:
    """Return the unit ControlGroup only when it is an absolute safe path."""
    unit = f"capivara-instance-{instance_id}.service"
    try:
        result = subprocess.run(
            ["systemctl", "show", unit, "--property=ControlGroup", "--value", "--no-pager"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = str(result.stdout or "").strip()
    if result.returncode != 0 or not value.startswith("/") or ".." in Path(value).parts:
        return None
    return value


def _cgroup_path(control_group: str) -> Path | None:
    """Resolve a systemd ControlGroup below the configured cgroup v2 root."""
    value = str(control_group or "").strip()
    if not value.startswith("/") or ".." in Path(value).parts:
        return None
    try:
        root = CGROUP_ROOT.resolve()
        candidate = (root / value.lstrip("/")).resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    return candidate


def _cgroup_usage(control_group: str) -> tuple[int | None, int | None]:
    """Return aggregate cgroup v2 CPU usage_usec and memory.current counters."""
    base = _cgroup_path(control_group)
    if base is None:
        return None, None
    cpu_usage = None
    memory_current = None
    try:
        for line in (base / "cpu.stat").read_text(encoding="utf-8").splitlines():
            key, _, raw = line.partition(" ")
            if key != "usage_usec":
                continue
            value = int(raw.strip())
            if value >= 0:
                cpu_usage = value
            break
    except (OSError, ValueError):
        pass
    try:
        value = int((base / "memory.current").read_text(encoding="utf-8").strip())
        if value >= 0:
            memory_current = value
    except (OSError, ValueError):
        pass
    return cpu_usage, memory_current


def _systemd_network(instance_id: str) -> tuple[int | None, int | None]:
    """Return per-unit IPAccounting counters without inventing zero values."""
    unit = f"capivara-instance-{instance_id}.service"
    try:
        result = subprocess.run(
            [
                "systemctl",
                "show",
                unit,
                "--property=IPIngressBytes",
                "--property=IPEgressBytes",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if result.returncode != 0:
        return None, None
    values: dict[str, int] = {}
    for line in (result.stdout or "").splitlines():
        key, separator, raw = line.partition("=")
        if not separator or key not in {"IPIngressBytes", "IPEgressBytes"}:
            continue
        try:
            value = int(raw.strip())
        except ValueError:
            continue
        if value >= 0:
            values[key] = value
    return values.get("IPIngressBytes"), values.get("IPEgressBytes")


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


def _cpu_percent_from_counter(
    instance_id: str,
    counter: int,
    *,
    units_per_second: int,
    source: str,
) -> float | None:
    """Convert a monotonic CPU-time counter into percent without mixing sources."""
    try:
        counter = int(counter)
        units_per_second = int(units_per_second)
    except (TypeError, ValueError):
        return None
    source = str(source or "").strip()
    if counter < 0 or units_per_second <= 0 or not source:
        return None

    now = time.monotonic()
    path = SAMPLE_STATE_DIR / f"{instance_id}.json"
    previous = None
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps({"monotonic": now, "counter": counter, "source": source}),
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    os.replace(temp, path)

    if not isinstance(previous, dict):
        return None
    previous_source = previous.get("source")
    if previous_source is None and "ticks" in previous:
        previous_source = "proc"
    if str(previous_source or "") != source:
        return None
    try:
        previous_counter = previous.get("counter")
        if previous_counter is None and source == "proc":
            previous_counter = previous.get("ticks")
        elapsed = now - float(previous["monotonic"])
        delta = counter - int(previous_counter)
        if elapsed <= 0 or delta < 0:
            return None
        return round((delta / units_per_second) / elapsed * 100.0, 2)
    except (KeyError, TypeError, ValueError):
        return None


def _cpu_percent(instance_id: str, process_ticks: int) -> float | None:
    try:
        hz = int(os.sysconf("SC_CLK_TCK"))
    except (ValueError, OSError):
        return None
    return _cpu_percent_from_counter(
        instance_id,
        process_ticks,
        units_per_second=hz,
        source="proc",
    )


def _cgroup_cpu_percent(instance_id: str, usage_usec: int) -> float | None:
    return _cpu_percent_from_counter(
        instance_id,
        usage_usec,
        units_per_second=1_000_000,
        source="cgroup-v2",
    )


def _network(interface: str | None) -> tuple[int | None, int | None]:
    interface = str(interface or "").strip()
    if not interface or "/" in interface or ".." in interface:
        return None, None
    base = Path("/sys/class/net") / interface / "statistics"
    try:
        rx = int((base / "rx_bytes").read_text().strip())
        tx = int((base / "tx_bytes").read_text().strip())
        return rx, tx
    except (OSError, ValueError):
        return None, None


def _storage_used(path_value: Any, *, max_entries: int = 200000) -> int | None:
    """Measure a complete tree or return unknown; never publish a partial total."""
    raw = str(path_value or "").strip()
    if not raw:
        return None
    try:
        root = Path(raw).resolve()
        if not root.is_dir():
            return None
    except OSError:
        return None
    total = 0
    seen = 0
    walk_failed = False

    def _walk_error(_error: OSError) -> None:
        nonlocal walk_failed
        walk_failed = True

    try:
        for current, dirs, files in os.walk(root, followlinks=False, onerror=_walk_error):
            safe_dirs: list[str] = []
            for name in dirs:
                try:
                    if not (Path(current) / name).is_symlink():
                        safe_dirs.append(name)
                except OSError:
                    return None
            dirs[:] = safe_dirs
            for name in files:
                seen += 1
                if seen > max_entries:
                    return None
                path = Path(current) / name
                try:
                    if not path.is_symlink():
                        total += path.stat().st_size
                except OSError:
                    return None
    except OSError:
        return None
    return None if walk_failed else total


def _read_cstring(payload: bytes, offset: int) -> tuple[bytes, int] | None:
    end = payload.find(b"\x00", offset)
    if end < 0:
        return None
    return payload[offset:end], end + 1


def _parse_a2s_info(payload: bytes) -> dict[str, int]:
    if len(payload) < 6 or payload[:4] != _A2S_HEADER or payload[4] != 0x49:
        return {}
    offset = 6  # response type + protocol byte
    for _ in range(4):  # name, map, folder, game
        parsed = _read_cstring(payload, offset)
        if parsed is None:
            return {}
        _, offset = parsed
    if offset + 4 > len(payload):
        return {}
    offset += 2  # app id
    return {
        "players_online": int(payload[offset]),
        "players_max": int(payload[offset + 1]),
    }


def _a2s_info(host: str, port: int, timeout_seconds: int = 2) -> dict[str, Any]:
    """Perform A2S_INFO, including the optional Source challenge round trip."""
    try:
        port = int(port)
        timeout = max(1, min(int(timeout_seconds), 5))
    except (TypeError, ValueError):
        return {}
    if not 1 <= port <= 65535:
        return {}
    started = time.monotonic()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(_A2S_INFO_REQUEST, (host, port))
            payload, _ = sock.recvfrom(4096)
            if len(payload) >= 5 and payload[:4] == _A2S_HEADER and payload[4] == 0x41:
                if len(payload) < 9:
                    return {}
                challenge = payload[5:9]
                sock.sendto(_A2S_INFO_REQUEST + challenge, (host, port))
                payload, _ = sock.recvfrom(4096)
    except (OSError, socket.timeout):
        return {}
    result: dict[str, Any] = _parse_a2s_info(payload)
    if result:
        result["latency_ms"] = round((time.monotonic() - started) * 1000.0, 2)
    return result


def _dayz_query(record: dict[str, Any], telemetry_config: dict[str, Any]) -> dict[str, Any]:
    ports = record.get("ports") if isinstance(record.get("ports"), dict) else {}
    query = ports.get("steam_query")
    raw_port = query.get("port") if isinstance(query, dict) else query
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return {}
    timeout = telemetry_config.get("query_timeout_seconds") or 2
    # The collector runs on the same Agent as the instance. Keeping this query
    # loopback-only avoids turning runtime metadata into an arbitrary UDP probe.
    return _a2s_info("127.0.0.1", port, timeout)


def _game_query(config: dict[str, Any]) -> dict[str, Any]:
    """Legacy explicit query helper retained for non-DayZ runtimes."""
    argv = config.get("query_argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        return {}
    executable = str(argv[0])
    if not executable.startswith("/"):
        return {}
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(1, min(int(config.get("query_timeout_seconds") or 5), 15)),
        )
        if result.returncode != 0:
            return {}
        value = json.loads(result.stdout or "{}")
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def collect_instance_telemetry(config: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for summary in instance_runtime.list_instances(config):
        instance_id = str(summary.get("instance_id") or "").strip()
        if not instance_id:
            continue
        record = instance_runtime.get_instance(instance_id) or {}
        adapter = str(record.get("adapter") or "").strip().lower()
        pid = _systemd_main_pid(instance_id) if adapter == "systemd" else None
        cpu = memory = uptime = None

        cgroup_cpu_counter = None
        if adapter == "systemd":
            control_group = _systemd_cgroup(instance_id)
            if control_group:
                cgroup_cpu_counter, cgroup_memory = _cgroup_usage(control_group)
                if cgroup_cpu_counter is not None:
                    cpu = _cgroup_cpu_percent(instance_id, cgroup_cpu_counter)
                if cgroup_memory is not None:
                    memory = cgroup_memory

        if pid:
            stat = _proc_stat(pid)
            if stat:
                ticks, started = stat
                if cgroup_cpu_counter is None:
                    cpu = _cpu_percent(instance_id, ticks)
                host_uptime = _host_uptime()
                if host_uptime is not None:
                    try:
                        uptime = max(0, int(host_uptime - (started / int(os.sysconf("SC_CLK_TCK")))))
                    except (ValueError, OSError, ZeroDivisionError):
                        uptime = None
            if memory is None:
                memory = _rss_bytes(pid)

        telemetry_config = record.get("telemetry") if isinstance(record.get("telemetry"), dict) else {}
        rx, tx = _systemd_network(instance_id) if adapter == "systemd" else (None, None)
        if rx is None and tx is None:
            rx, tx = _network(telemetry_config.get("network_interface"))

        game_id = str(record.get("game_id") or "").strip().lower()
        profile = str(record.get("profile") or "").strip().lower()
        game = _dayz_query(record, telemetry_config) if game_id in {"dayz", "dayz.stable"} or profile == "dayz" else _game_query(telemetry_config)

        try:
            view = instance_runtime.status(config, instance_id)
            state = str(view.get("observed_state") or "unknown").lower()
            health = "healthy" if state == "running" else ("degraded" if state in {"starting", "failed", "unavailable"} else "unknown")
        except Exception:
            health = "unknown"

        private_state_root = record.get("instance_state_root") or record.get("path")
        results.append({
            "instance_id": instance_id,
            "storage_pool_id": str(record.get("storage_pool_id") or "") or None,
            "cpu_percent": cpu,
            "memory_bytes": memory,
            "storage_used_bytes": _storage_used(private_state_root),
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
