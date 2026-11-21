"""Prevent #928 CI from executing imported TestCase fixtures twice.

unittest discovers TestCase classes bound in a module namespace, even when
that class was defined in another module and imported solely as a fixture.
Fixture dependencies must be imported as modules instead. This is a
discovery-only audit: it does not execute the nested test suite.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import unittest


TESTS_DIR = Path(__file__).resolve().parent


def _cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _cases(item)
        else:
            yield item


class UptimeTestDiscoverySafetyTests(unittest.TestCase):
    def test_every_case_discovered_exactly_once(self):
        loader = unittest.TestLoader()
        suite = loader.discover(
            start_dir=str(TESTS_DIR),
            pattern="update_game_uptime_*test.py",
            top_level_dir=str(TESTS_DIR),
        )
        ids = [test.id() for test in _cases(suite)]
        counts = Counter(ids)
        repeated = {name: count for name, count in counts.items() if count > 1}
        self.assertFalse(repeated, f"duplicate unittest cases: {repeated}")

        # Protect the test coverage removed accidentally by import refactors.
        # These are *discovered* here and still actually executed by the CI
        # unittest invocation (and the separate opt-in systemd job).
        required = {
            "update_game_uptime_isolated_compose_test.IsolatedCompositionTests.test_success_composes_real_updater_functions_and_fake_reload",
            "update_game_uptime_sqlite_http_integration_test.ActualDispatcherSqliteHttpTests.test_actual_controller_part11_post_route_with_durable_agent_credential",
            "update_game_uptime_evidence_rehearsal_test.ObservedEvidenceFixtureTests.test_replayed_heartbeat_offer_blocked_before_any_backup",
            "update_game_uptime_main_path_test.MainPathRehearsalTest.test_disposable_no_drain_main_injected_failure_rolls_back_without_draining",
            "update_game_uptime_systemd_e2e_test.DisposableSystemdNoDrainTest.test_real_dashboard_and_hybrid_worker_restart_around_disposable_update",
        }
        self.assertTrue(required.issubset(counts), sorted(required - counts.keys()))
        self.assertGreaterEqual(len(ids), 250)


if __name__ == "__main__":
    unittest.main()
