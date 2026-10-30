"""Regression tests for global update artifact cleanup eligibility."""
from dataclasses import replace
import unittest
from artifact_cleanup_policy import CleanupEvidence, eligible_for_cleanup

BASE = CleanupEvidence(
    transfer_status='completed', operation_status='applied',
    operation_terminal=True, applied_revision_aligned=True,
    active_consumers=0, rollback_consumers=0, shared_consumers=0,
    ownership_verified=True,
)


class CleanupPolicyTests(unittest.TestCase):
    def test_verified_completed_installation(self):
        self.assertTrue(eligible_for_cleanup(BASE))

    def test_games_are_not_a_policy_condition(self):
        for game in ('minecraft', 'dayz', 'palworld', 'future-game'):
            with self.subTest(game=game):
                self.assertTrue(eligible_for_cleanup(BASE))

    def test_running_transfer(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, transfer_status='transferring')))

    def test_pending_operation(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, operation_terminal=False)))

    def test_unaligned_revision(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, applied_revision_aligned=False)))

    def test_live_reference(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, active_consumers=1)))

    def test_rollback_reference(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, rollback_consumers=1)))

    def test_shared_reference(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, shared_consumers=1)))

    def test_backup_protected(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, is_backup=True)))

    def test_installed_runtime_protected(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, is_installed_runtime=True)))

    def test_ownership_required(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, ownership_verified=False)))

    def test_unknown_status_protected(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, operation_status='unknown')))

    def test_cancelled_after_terminal_confirmation(self):
        self.assertTrue(eligible_for_cleanup(replace(BASE, transfer_status='cancelled', operation_status='cancelled')))

    def test_abandoned_after_terminal_confirmation(self):
        self.assertTrue(eligible_for_cleanup(replace(BASE, transfer_status='expired', operation_status='abandoned')))

    def test_failed_but_still_in_use(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, operation_status='failed', rollback_consumers=1)))

    def test_unknown_reference_count(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, rollback_consumers=-1)))

    def test_boolean_not_accepted_as_reference_count(self):
        self.assertFalse(eligible_for_cleanup(replace(BASE, active_consumers=False)))


if __name__ == '__main__':
    unittest.main()
