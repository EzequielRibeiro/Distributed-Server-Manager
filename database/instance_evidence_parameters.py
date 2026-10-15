"""Controller-side validation of instance evidence query parameters.

No DB schema or queue behavior is changed by this module.
"""
from __future__ import annotations

from datetime import datetime, timezone

EVIDENCE_ACTION = 'systemd_lifecycle_evidence'
MAX_SECONDS = 900


def _utc(value):
    if not isinstance(value, str):
        raise ValueError('timestamp must be a string')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('invalid timestamp') from None
    if parsed.tzinfo is None:
        raise ValueError('timestamp timezone required')
    return parsed.astimezone(timezone.utc)


def normalize_command_parameters(action, parameters=None):
    """Return normalized params for evidence; reject params on other actions."""
    if action != EVIDENCE_ACTION:
        if parameters is not None:
            raise ValueError('parameters not supported for action')
        return None
    if not isinstance(parameters, dict) or set(parameters) != {'since', 'until'}:
        raise ValueError('evidence requires since and until only')
    since, until = _utc(parameters['since']), _utc(parameters['until'])
    if since > until or (until - since).total_seconds() > MAX_SECONDS:
        raise ValueError('invalid evidence interval')
    return {'since': since.isoformat().replace('+00:00', 'Z'), 'until': until.isoformat().replace('+00:00', 'Z')}
