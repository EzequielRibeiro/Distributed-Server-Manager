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
