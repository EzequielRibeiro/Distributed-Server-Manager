"""Fail-closed functional boot proof for an owned Minecraft Server Pack runtime.

A log 'Done' is advisory. A positive observation additionally requires that the
same live JVM owns the configured TCP listener and answers a Minecraft status
handshake. The Controller must separately validate agent/revision/hash/freshness.
This probe never changes game state and never grants release authorization.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from typing import Any

_COMMON = Path(__file__).resolve().parents[2] / 'common'
if str(_COMMON) not in sys.path:
    sys.path.insert(0, str(_COMMON))
from minecraft_java_status import query_java_status
from minecraft_serverpack_boot_witness import observe_boot_witness

_HEX = re.compile(r'^[0-9a-f]{64}$')


def _configured_port(runtime: Path) -> int | None:
    props = runtime / 'server.properties'
    if props.is_symlink() or not props.is_file() or props.stat().st_size > 65536:
        return None
    ports = []
    for line in props.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        if key.strip() == 'server-port':
            try:
                port = int(value.strip())
                if not 1 <= port <= 65535:
                    return None
                ports.append(port)
            except ValueError:
                return None
    return ports[0] if len(ports) == 1 else None


def _owned_listener(java_pid: int, port: int) -> bool:
    """Bind the status socket to a JVM FD; a competing server is not proof."""
    if type(java_pid) is not int or java_pid <= 1:
        return False
    fd = Path(f'/proc/{java_pid}/fd')
    inodes = set()
    for entry in fd.iterdir():
        try:
            target = os.readlink(entry)
        except FileNotFoundError:
            continue  # Concurrent FD teardown is harmless; final proof rechecks.
        if target.startswith('socket:[') and target.endswith(']'):
            inodes.add(target[8:-1])
    if not inodes:
        return False
    for table in ('tcp', 'tcp6'):
        path = Path(f'/proc/{java_pid}/net/{table}')
        for line in path.read_text(encoding='ascii').splitlines()[1:]:
            fields = line.split()
            if len(fields) < 10 or fields[3] != '0A' or fields[9] not in inodes:
                continue
            try:
                local_port = int(fields[1].rsplit(':', 1)[-1], 16)
            except ValueError:
                continue
            if local_port == port:
                return True
    return False


def attest_live_serverpack_readiness(
    runtime: Path, *, instance_id: str, game_port: Any,
    bundle_revision: int, manifest_sha256: str,
) -> dict[str, Any]:
    """An authenticated Agent may attach this to its already scoped observation.

    This is an operational signal, not the final Controller release decision.
    """
    failed = {'status': 'not_attested', 'boot_verified': False,
              'ready_for_release': False}
    if (type(bundle_revision) is not int or bundle_revision < 1
            or not isinstance(manifest_sha256, str) or not _HEX.fullmatch(manifest_sha256)
            or type(game_port) is not int or not 1 <= game_port <= 65535):
        return {**failed, 'reason': 'invalid_revision_manifest_or_port'}
    try:
        runtime = Path(runtime)
        if (not runtime.is_absolute() or runtime.is_symlink()
                or not runtime.is_dir() or _configured_port(runtime) != game_port):
            return {**failed, 'reason': 'port_not_bound_to_runtime'}
        before = observe_boot_witness(runtime, instance_id=instance_id)
        if before.get('status') != 'boot_process_observed':
            return {**failed, 'reason': 'current_boot_witness_missing'}
        java_pid = before['java_pid']
        if not _owned_listener(java_pid, game_port):
            return {**failed, 'reason': 'listener_not_owned_by_java'}
        status = query_java_status(game_port, timeout_seconds=2)
        if not (type(status.get('players_online')) is int
                and type(status.get('players_max')) is int):
            return {**failed, 'reason': 'minecraft_status_not_ready'}
        after = observe_boot_witness(runtime, instance_id=instance_id)
        if (after.get('status') != 'boot_process_observed'
                or (before['java_pid'], before['java_started_at'], before['done_at'])
                   != (after['java_pid'], after['java_started_at'], after['done_at'])
                or not _owned_listener(java_pid, game_port)):
            return {**failed, 'reason': 'process_changed_during_probe'}
        return {'status': 'functional_boot_attested',
                'proof_scope': 'owned_jvm_and_live_minecraft_status',
                'boot_verified': True, 'ready_for_release': False,
                'instance_id': instance_id, 'bundle_revision': bundle_revision,
                'manifest_sha256': manifest_sha256,
                'java_pid': java_pid,
                'java_started_at': before['java_started_at'],
                'done_at': before['done_at'], 'game_port': game_port}
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return {**failed, 'reason': 'live_probe_unavailable'}


def reserved_game_port(record: dict[str, Any]) -> int | None:
    """Use the Agent's owned port reservation, never a user supplied port."""
    bindings = record.get('ports')
    game = bindings.get('game') if isinstance(bindings, dict) else None
    if not isinstance(game, dict) or str(game.get('protocol', '')).lower() != 'tcp':
        return None
    value = game.get('port')
    return value if type(value) is int and 1 <= value <= 65535 else None


__all__ = ['attest_live_serverpack_readiness', 'reserved_game_port']
