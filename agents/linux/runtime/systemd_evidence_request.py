"""Strict schema for read-only systemd lifecycle evidence requests."""
from datetime import datetime, timezone
import re

TOKEN = re.compile(r'^[A-Za-z0-9._-]{1,191}$')


def validate_evidence_request(command):
    if not isinstance(command, dict):
        raise ValueError('request must be an object')
    required = {'command_id', 'instance_id', 'action', 'since', 'until'}
    allowed = required | {'agent_id'}
    if not required.issubset(command) or not set(command).issubset(allowed):
        raise ValueError('invalid request fields')
    if command['action'] != 'systemd_lifecycle_evidence':
        raise ValueError('unsupported action')
    for name in ('command_id', 'instance_id'):

        value = command[name]
        if not isinstance(value, str) or not TOKEN.fullmatch(value):
            raise ValueError('invalid ' + name)
    if 'agent_id' in command and (not isinstance(command['agent_id'], str) or not TOKEN.fullmatch(command['agent_id'])):
        raise ValueError('invalid agent_id')
    try:
        start = datetime.fromisoformat(command['since'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(command['until'].replace('Z', '+00:00'))
    except (AttributeError, ValueError, TypeError):
        raise ValueError('invalid timestamps') from None
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError('timezone required')
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if start > end or (end-start).total_seconds() > 900:
        raise ValueError('invalid query interval')
    return dict(command_id=command['command_id'], instance_id=command['instance_id'], action=command['action'], since=start.isoformat().replace('+00:00','Z'), until=end.isoformat().replace('+00:00','Z'))
