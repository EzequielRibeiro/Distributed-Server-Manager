"""Agent-local durable history of systemd observations (not stop attestations).

Only the Agent should invoke this for instances it owns. A sequence of two
running snapshots must never be interpreted as proof of an intervening stop.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

_ID = re.compile(r'^[A-Za-z0-9._-]{1,191}$')
MAX_OBSERVATIONS = 64


def record_observation(state_dir: Path, instance_id: str, adapter_state: dict, *, observed_at: str | None = None) -> dict:
    if not _ID.fullmatch(instance_id):
        raise ValueError('invalid instance ID')
    if not isinstance(adapter_state, dict) or adapter_state.get('adapter') != 'systemd':
        raise ValueError('systemd state required')
    if adapter_state.get('unit') != f'capivara-instance-{instance_id}.service':
        raise ValueError('unit does not match instance')
    root = Path(state_dir) / 'systemd-observations'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    path = root / f'{instance_id}.json'
    try:
        history = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(history, list):
            history = []
    except (OSError, ValueError):
        history = []
    entry = {
        'observed_at': observed_at or datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'instance_id': instance_id,
        'unit': adapter_state['unit'],
        'main_pid': adapter_state.get('main_pid'),
        'active_state': adapter_state.get('active_state'),
        'invocation_id': adapter_state.get('invocation_id'),
        'active_enter_timestamp': adapter_state.get('active_enter_timestamp'),
    }
    if history and all(history[-1].get(k) == entry.get(k) for k in ('main_pid', 'active_state', 'invocation_id')):
        return entry
    history = (history + [entry])[-MAX_OBSERVATIONS:]
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    try:
        with tmp.open('x', encoding='utf-8') as stream:
            os.chmod(tmp, 0o600)
            json.dump(history, stream, separators=(',', ':'))
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return entry
