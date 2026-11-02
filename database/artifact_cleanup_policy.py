"""Game-neutral, fail-closed decision policy for disposable transfer artifacts.

Only allows *eligibility*; callers must recheck references and ownership
under a database transaction before enqueueing a cleanup job.
Never operate directly on filesystem paths from this module.
"""
from dataclasses import dataclass

FINAL_TRANSFERS = frozenset({'completed', 'expired', 'cancelled', 'failed'})
SAFE_TERMINAL_OPERATIONS = frozenset({'applied', 'cancelled', 'abandoned', 'failed'})


@dataclass(frozen=True)
class CleanupEvidence:
    transfer_status: str
    operation_status: str
    operation_terminal: bool
    applied_revision_aligned: bool
    active_consumers: int
    rollback_consumers: int
    shared_consumers: int
    is_installed_runtime: bool = False
    is_backup: bool = False
    ownership_verified: bool = False


def eligible_for_cleanup(evidence: CleanupEvidence) -> bool:
    """Fail closed if any proof of no longer being needed is unavailable.

    The operation may be from any game. For a completed installation, the
    Controller and Agent must agree on the applied revision. For a failed or
    cancelled operation, terminality must have been persisted by the caller.
    """
    if not isinstance(evidence, CleanupEvidence):
        return False
    if not evidence.ownership_verified or evidence.is_backup or evidence.is_installed_runtime:
        return False
    if evidence.transfer_status not in FINAL_TRANSFERS:
        return False
    if evidence.operation_status not in SAFE_TERMINAL_OPERATIONS:
        return False
    if evidence.operation_terminal is not True:
        return False
    if any(type(n) is not int or n != 0 for n in (
        evidence.active_consumers, evidence.rollback_consumers, evidence.shared_consumers
    )):
        return False
    if evidence.operation_status == 'applied' and evidence.applied_revision_aligned is not True:
        return False
    return True


def classify_expired_upload(*, transfer_status: str,
                            has_current_reference: bool,
                            has_historical_reference: bool) -> str:
    """Audit-only classification: historical references are *not* deletable.

    An explicit, verified applied revision and rollback decision are still
    required before relaxing historical-reference protection.
    """
    if transfer_status != 'expired':
        return 'not_expired'
    if has_current_reference:
        return 'current_reference'
    if has_historical_reference:
        return 'historical_reference'
    return 'unreferenced_expired'
