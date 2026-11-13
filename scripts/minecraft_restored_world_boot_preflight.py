#!/usr/bin/env python3
"""Read-only, fail-closed preflight before booting a *restored* ATM11 world.

This tool never restores, starts, stops, installs, extracts or deletes anything.
It only decides whether a disposable host can safely begin that separate test.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import stat
import sys
import tarfile

GIB = 1024 ** 3
MIN_AVAILABLE_MEMORY_GIB = 12
MIN_DISK_HEADROOM_GIB = 12
MAX_LOAD_FRACTION = 0.70
EXPECTED_RUNTIME = "minecraft.java.neoforge"
EXPECTED_GAME = "minecraft"
MANIFEST = ".capivara-backup-manifest.json"
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")
PROTECTED_ROOTS = (
    Path("/opt/dsm/runtime"),
    Path("/opt/dsm/game-data"),
    Path("/home/mine/steamcmd/serverfiles"),
    Path("/srv/capivara-data/instances"),
)


def _is_inside(path: Path, ancestor: Path) -> bool:
    return path == ancestor or ancestor in path.parents


def _available_memory_bytes(meminfo: str) -> int:
    for line in meminfo.splitlines():
        match = re.fullmatch(r"MemAvailable:\s*(\d+)\s+kB\s*", line.strip())
        if match:
            return int(match.group(1)) * 1024
    raise ValueError("MemAvailable missing from /proc/meminfo")


def _manifest(archive: Path) -> dict:
    # next() reads only the first TAR member, without decompressing the world.
    with tarfile.open(archive, "r:gz") as stream:
        item = stream.next()
        if item is None or not item.isfile() or item.name != MANIFEST or item.size > 8192:
            raise ValueError("Capivara backup manifest is missing or misplaced")
        source = stream.extractfile(item)
        if source is None:
            raise ValueError("Capivara backup manifest cannot be read")
        value = json.load(source)
    if not isinstance(value, dict) or value.get("kind") != "CapivaraInstanceBackup":
        raise ValueError("invalid Capivara backup manifest")
    return value


def _port_available(port: int) -> bool:
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("sandbox TCP port must be unprivileged")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def preflight(
    archive: Path,
    sandbox_parent: Path,
    *,
    instance_id: str,
    backup_id: str,
    port: int = 25596,
    meminfo: str | None = None,
    disk_free_bytes: int | None = None,
    load_one: float | None = None,
    cpu_count: int | None = None,
    port_free: bool | None = None,
    systemd_available: bool | None = None,
) -> dict:
    """Read-only resource gate. Overrides exist only for deterministic tests."""
    if not instance_id or not re.fullmatch(r"[A-Za-z0-9._-]{1,191}", instance_id):
        raise ValueError("invalid source instance ID")
    if instance_id in {".", ".."} or not UUID.fullmatch(backup_id):
        raise ValueError("invalid backup identifier")
    backup = Path(archive)
    parent = Path(sandbox_parent)
    if backup.is_symlink() or not backup.is_file() or not stat.S_ISREG(backup.stat().st_mode):
        raise ValueError("backup must be an existing regular non-symlink file")
    if parent.is_symlink() or not parent.is_dir() or not stat.S_ISDIR(parent.stat().st_mode):
        raise ValueError("sandbox parent must be an existing non-symlink directory")
    parent = parent.resolve(strict=True)
    if parent == Path("/") or any(_is_inside(parent, root) for root in PROTECTED_ROOTS):
        raise ValueError("refuse sandbox inside installed DSM or live game data")
    # Archive may reside in a production backup folder, but it is never written.
    item = _manifest(backup)
    if (
        item.get("game_id") != EXPECTED_GAME
        or item.get("runtime_id") != EXPECTED_RUNTIME
        or item.get("source_instance") != instance_id
        or item.get("backup_id") != backup_id
    ):
        raise ValueError("backup identity differs from the requested Minecraft instance")
    archive_bytes = backup.stat().st_size
    if archive_bytes < 128:
        raise ValueError("backup archive is suspiciously small")
    memory = _available_memory_bytes(
        meminfo if meminfo is not None else Path("/proc/meminfo").read_text()
    )
    if disk_free_bytes is None:
        vfs = os.statvfs(parent)
        disk_free_bytes = int(vfs.f_bavail) * int(vfs.f_frsize)
    if type(disk_free_bytes) is not int or disk_free_bytes < 0:
        raise ValueError("invalid available disk capacity")
    if load_one is None:
        load_one = os.getloadavg()[0]
    if cpu_count is None:
        cpu_count = os.cpu_count()
    if cpu_count is None or cpu_count <= 0 or not 0 <= load_one < 1e8:
        raise ValueError("cannot prove host load")
    if port_free is None:
        port_free = _port_available(port)
    else:
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("sandbox TCP port must be unprivileged")
    if systemd_available is None:
        systemd_available = Path("/run/systemd/system").is_dir()
    disk_required = max(MIN_DISK_HEADROOM_GIB * GIB, archive_bytes * 2 + 4 * GIB)
    reasons = []
    if memory < MIN_AVAILABLE_MEMORY_GIB * GIB:
        reasons.append("insufficient_available_memory")
    if disk_free_bytes < disk_required:
        reasons.append("insufficient_disposable_disk")
    if load_one / cpu_count > MAX_LOAD_FRACTION:
        reasons.append("host_too_busy")
    if not port_free:
        reasons.append("sandbox_loopback_port_in_use")
    if not systemd_available:
        reasons.append("systemd_unavailable")
    return {
        "status": "blocked" if reasons else "preflight_pass",
        "scope": "read_only_no_boot_no_restore",
        "instance_id": instance_id,
        "backup_id": backup_id,
        "game": EXPECTED_GAME,
        "runtime": EXPECTED_RUNTIME,
        "archive_manifest_valid": True,
        "archive_sha256_verified_by_this_preflight": False,
        "memory_available_bytes": memory,
        "memory_required_bytes": MIN_AVAILABLE_MEMORY_GIB * GIB,
        "disk_available_bytes": disk_free_bytes,
        "disk_required_bytes": disk_required,
        "host_load_one": load_one,
        "cpu_count": cpu_count,
        "loopback_tcp_port": port,
        "systemd_available": bool(systemd_available),
        "reasons": reasons,
        "next_step": (
            "copy the verified backup to a disposable host and run a separate "
            "isolated world boot; this preflight alone does not certify gameplay"
            if not reasons else "do_not_boot_on_this_host"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sandbox-parent", type=Path, required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--port", type=int, default=25596)
    args = parser.parse_args(argv)
    try:
        result = preflight(
            args.archive, args.sandbox_parent, instance_id=args.instance_id,
            backup_id=args.backup_id, port=args.port,
        )
    except (ValueError, OSError, tarfile.TarError, json.JSONDecodeError) as exc:
        result = {"status": "blocked_invalid_evidence", "reason": str(exc),
                  "scope": "read_only_no_boot_no_restore"}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "preflight_pass" else 2


if __name__ == "__main__":
    sys.exit(main())
