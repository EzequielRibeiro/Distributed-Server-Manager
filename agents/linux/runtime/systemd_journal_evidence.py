"""Parse journal events for a single systemd instance; read-only and fail closed.

This parser is not an authenticator. Only Agent-side journal access through
its authenticated command channel may establish provenance. Never infer a
stop from a PID or InvocationID change.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

_ID = re.compile(r'^[A-Za-z0-9._-]{1,191}$')


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except ValueError:
        return None


def select_systemd_transitions(instance_id: str, events: list[dict], *, since: str, until: str) -> list[dict]:
    """Select explicit manager lifecycle messages in a bounded UTC window.

    Returns event observations, not verified completion or authorization.
    """
    if not _ID.fullmatch(instance_id):
        raise ValueError('invalid instance_id')
    start, end = _timestamp(since), _timestamp(until)
    if start is None or end is None or start > end:
        raise ValueError('invalid time window')
    unit = f'capivara-instance-{instance_id}.service'
    matches = []
    for item in events:
        if not isinstance(item, dict):
            continue
        # Unit-scoped journal entries are not necessarily systemd manager events.
        # Require manager origin plus explicit lifecycle message identifiers.
        if item.get('_COMM') != 'systemd' or str(item.get('_PID')) != '1':
            continue
        event_unit = item.get('UNIT')
        if event_unit != unit:
            continue
        message_id = item.get('MESSAGE_ID')
        kind = {
            '7d4958e842da4a758f6c1cdc7b36dcc5': 'starting',
            '39f53479d3a045ac8e11786248231fbf': 'started',
            'de5b426a63be47a7b6ac3eaac82e2f': 'stopping',
            '9d1aaa27d60140bd96365438aad20286': 'stopped',
        }.get(message_id)
        if kind is None:
            continue
        try:
            micros = int(item['__REALTIME_TIMESTAMP'])
            moment = datetime.fromtimestamp(micros / 1_000_000, tz=timezone.utc)
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            continue
        if start <= moment <= end:
            matches.append({'unit': unit, 'event': kind, 'at': moment.isoformat().replace('+00:00', 'Z')})
    return sorted(matches, key=lambda item: item['at'])
