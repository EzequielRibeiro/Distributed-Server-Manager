"""Pure state decision for historical evidence lookup after native timeout.

Historical systemd stop/start is not proof of native DayZ shutdown.
No decision in this module permits offline maintenance or another start.
"""

def decide_timeout_evidence(*, elapsed, timeout_seconds, evidence_state, restart_confirmed=False):
    if elapsed < timeout_seconds:
        return 'continue-native-probes'
    if evidence_state == 'not-requested':
        return 'request-history'
    if evidence_state in ('queued', 'delivered'):
        return 'await-history'
    if evidence_state == 'completed' and restart_confirmed:
        return 'abort-systemd-restarted-native-unverified'
    return 'native-shutdown-timeout'
