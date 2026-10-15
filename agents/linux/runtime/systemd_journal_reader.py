"""Read bounded systemd manager events for an owned instance.

The caller must check instance ownership before invoking this function.
Results are observations, NOT authentication of maintenance intent.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from datetime import datetime

from systemd_journal_evidence import select_systemd_transitions, _timestamp

_ID = re.compile(r'^[A-Za-z0-9._-]{1,191}$')
MAX_EVENTS = 512
MAX_WINDOW_SECONDS = 900
MAX_OUTPUT_BYTES = 2_000_000


def read_systemd_transitions(instance_id: str, *, since: str, until: str, runner=None) -> list[dict]:
    if not isinstance(instance_id, str) or not _ID.fullmatch(instance_id):
        raise ValueError('invalid instance ID')
    start, end = _timestamp(since), _timestamp(until)
    if start is None or end is None or start > end or (end-start).total_seconds() > MAX_WINDOW_SECONDS:
        raise ValueError('invalid or oversized time window')
    unit = f'capivara-instance-{instance_id}.service'
    args = ['journalctl', '--no-pager', '--output=json', '--since', start.isoformat(), '--until', end.isoformat(), f'UNIT={unit}']
    if runner is None:
        # Avoid unbounded capture_output: journal volume is not controlled by the Agent.
        with tempfile.TemporaryFile(mode='w+b') as sink:
            result = subprocess.run(args, stdout=sink, stderr=subprocess.DEVNULL,
                                    check=False, timeout=12)
            if result.returncode != 0:
                raise RuntimeError('journal query failed')
            if sink.tell() > MAX_OUTPUT_BYTES:
                raise ValueError('journal response too large')
            sink.seek(0)
            output = sink.read(MAX_OUTPUT_BYTES + 1).decode('utf-8')
    else:
        result = runner(args)
        if result.returncode != 0:
            raise RuntimeError('journal query failed')
        output = result.stdout
        if not isinstance(output, str) or len(output.encode('utf-8')) > MAX_OUTPUT_BYTES:
            raise ValueError('journal response too large')
    events = []
    for line in output.splitlines():
        if not line.strip():
            continue
        if len(events) >= MAX_EVENTS:
            raise ValueError('journal event limit exceeded')
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError('invalid journal entry')
        events.append(value)
    return select_systemd_transitions(instance_id, events, since=since, until=until)
