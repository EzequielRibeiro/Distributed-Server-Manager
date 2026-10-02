#!/usr/bin/env python3
"""Failure-injection tests for an offline-only staged migration model."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
from minecraft_staged_migration_rehearsal import RehearsalError, rehearse_staged_migration


def scenario(*, fail=None, preflight=True, space=True, rollback_fails=False):
    events = []
    def step(name):
        def call():
            events.append(name)
            if name == fail or (name == "rollback" and rollback_fails):
                raise RuntimeError("injected " + name)
            if name == "doctor":
                return True
        return call
    callbacks = dict(
        revalidate=lambda: {"valid": preflight, "install_allowed": False},
        capacity=lambda: {"sufficient": space, "install_allowed": False},
        stage=step("stage"),
        checkpoint=step("checkpoint"),
        activate=step("activate"),
        doctor=step("doctor"),
        commit=step("commit"),
        rollback=step("rollback"),
        cleanup=step("cleanup"),
        test_only=True,
    )
    if fail == "readiness":
        callbacks["doctor"] = lambda: events.append("doctor") or False
    return events, callbacks


class StagedMigrationRehearsalTest(unittest.TestCase):
    def test_never_runs_without_explicit_test_only(self):
        events, args = scenario()
        args.pop("test_only")
        with self.assertRaisesRegex(RehearsalError, "test_only"):
            rehearse_staged_migration(**args)
        self.assertEqual(events, [])

    def test_preconditions_fail_before_staging(self):
        for option in ("preflight", "space"):
            with self.subTest(option=option):
                events, args = scenario(**{option: False})
                with self.assertRaises(RehearsalError):
                    rehearse_staged_migration(**args)
                self.assertEqual(events, [])

    def test_success_has_correct_order_and_no_rollback(self):
        events, args = scenario()
        result = rehearse_staged_migration(**args)
        self.assertEqual(result["status"], "rehearsal_completed")
        self.assertFalse(result["production_enabled"])
        self.assertEqual(events, ["stage", "checkpoint", "activate", "doctor", "commit", "cleanup"])

    def test_fault_injection_restores_only_after_checkpoint(self):
        for failed, expected in (
            ("stage", ["stage", "cleanup"]),
            ("checkpoint", ["stage", "checkpoint", "cleanup"]),
            ("activate", ["stage", "checkpoint", "activate", "rollback", "cleanup"]),
            ("readiness", ["stage", "checkpoint", "activate", "doctor", "rollback", "cleanup"]),
            ("commit", ["stage", "checkpoint", "activate", "doctor", "commit", "rollback", "cleanup"]),
        ):
            with self.subTest(failed=failed):
                events, args = scenario(fail=failed)
                with self.assertRaises(RehearsalError):
                    rehearse_staged_migration(**args)
                self.assertEqual(events, expected)

    def test_rollback_failure_requires_manual_intervention(self):
        events, args = scenario(fail="activate", rollback_fails=True)
        with self.assertRaisesRegex(RehearsalError, "manual intervention"):
            rehearse_staged_migration(**args)
        self.assertEqual(events[-2:], ["rollback", "cleanup"])

    def test_cleanup_failure_blocks_acceptance(self):
        events, args = scenario(fail="cleanup")
        with self.assertRaisesRegex(RehearsalError, "cleanup failed"):
            rehearse_staged_migration(**args)


if __name__ == "__main__":
    unittest.main()
