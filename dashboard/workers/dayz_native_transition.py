"""Validate authenticated DayZ stop/start evidence; no data collection here."""
from datetime import datetime, timezone


def _utc(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone required')
    return parsed.astimezone(timezone.utc)


def verified_native_transition(*, instance_id, old_pid, new_pid, expected_at, deadline_at, evidence, authenticated=False, expected_old_invocation_id=None, observed_new_invocation_id=None):
    """Reject PID-only inference and unverified lifecycle claims."""
    if not authenticated:
        return False
    try:
        if str(evidence['instance_id']) != str(instance_id):
            return False
        previous, current = int(old_pid), int(new_pid)
        if previous <= 0 or current <= 0 or previous == current:
            return False
        if int(evidence['old_pid']) != previous or int(evidence['new_pid']) != current:
            return False
        if expected_old_invocation_id is not None or observed_new_invocation_id is not None:
            if not expected_old_invocation_id or not observed_new_invocation_id:
                return False
            if expected_old_invocation_id == observed_new_invocation_id:
                return False
            if str(evidence['old_invocation_id']) != str(expected_old_invocation_id):
                return False
            if str(evidence['new_invocation_id']) != str(observed_new_invocation_id):
                return False
        stopped = _utc(evidence['stopped_at'])
        restarted = _utc(evidence['restarted_at'])
        return _utc(expected_at) <= stopped <= _utc(deadline_at) and restarted >= stopped
    except (KeyError, ValueError, TypeError, OverflowError):
        return False


def observed_systemd_restart(*, instance_id, expected_at, deadline_at, observations, authenticated=False):
    """Detect a historical unit stop/start, not proof of DayZ-native causation.

    Only callers that authenticated the Agent result may set authenticated=True.
    Never use this predicate alone to authorize offline work or another start.
    """
    if not authenticated or not isinstance(observations, dict):
        return False
    if observations.get('kind') != 'CapivaraSystemdLifecycleObservations':
        return False
    if str(observations.get('instance_id')) != str(instance_id):
        return False
    if observations.get('verified_native_shutdown') is not False:
        return False
    events = observations.get('events')
    if not isinstance(events, list):
        return False
    try:
        lower, upper = _utc(expected_at), _utc(deadline_at)
        if lower > upper:
            return False
        stops = [_utc(item['at']) for item in events
                 if isinstance(item, dict) and item.get('event') == 'stopped'
                 and item.get('unit') == f'capivara-instance-{instance_id}.service']
        starts = [_utc(item['at']) for item in events
                  if isinstance(item, dict) and item.get('event') == 'started'
                  and item.get('unit') == f'capivara-instance-{instance_id}.service']
        return any(lower <= stopped <= upper and stopped <= started <= upper
                   for stopped in stops for started in starts)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def offline_work_gate(*, latest_status, status_completed, historical_restart=False):
    """Fail closed before filesystem mutations or a generic start.

    A historical restart is evidence of a race, never permission to proceed.
    The caller must obtain a fresh Agent status result and independently
    establish its authenticity. This function does not authenticate it.
    """
    if historical_restart:
        return 'abort-already-restarted'
    if not status_completed:
        return 'wait-for-fresh-status'
    if latest_status == 'stopped':
        return 'allow-offline-work'
    if latest_status in ('running', 'starting'):
        return 'abort-instance-active'
    return 'wait-for-fresh-status'
