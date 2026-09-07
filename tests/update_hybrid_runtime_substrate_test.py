#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPDATE = (ROOT / "update.sh").read_text(encoding="utf-8")


class UpdateHybridRuntimeSubstrateTest(unittest.TestCase):
    def test_updater_has_hybrid_substrate_reconcile(self):
        self.assertIn(
            "reconcile_hybrid_runtime_substrate()",
            UPDATE,
        )
        self.assertIn(
            'installer/install_hybrid_runtime_substrate.sh',
            UPDATE,
        )
        self.assertIn(
            'runtime/hybrid-agent-state/agent.json',
            UPDATE,
        )
        self.assertIn(
            'dsm-hybrid-agent-materialize@.service',
            UPDATE,
        )
        self.assertIn(
            'DSM_ROOT="${INSTALL_DIR}" bash "${INSTALLER}"',
            UPDATE,
        )

    def test_reconcile_runs_after_systemd_and_before_worker_restart(self):
        main_start = UPDATE.index("main() {")
        main = UPDATE[main_start:]

        update_systemd = main.index("    update_systemd")
        reconcile = main.index("    reconcile_hybrid_runtime_substrate")
        migrate_workers = main.index("    migrate_dashboard_worker_services")
        restart = main.index("    restart_services")

        self.assertLess(update_systemd, reconcile)
        self.assertLess(reconcile, migrate_workers)
        self.assertLess(migrate_workers, restart)

    def test_non_hybrid_installations_are_skipped(self):
        start = UPDATE.index("reconcile_hybrid_runtime_substrate()")
        end = UPDATE.index(
            "# Migrar workers legados do Dashboard",
            start,
        )
        function = UPDATE[start:end]

        self.assertIn(
            '[[ ! -f "${AGENT_CONFIG}" && ! -f "${LEGACY_MATERIALIZER}" ]]',
            function,
        )
        self.assertIn("return 0", function)


    def test_rollback_reconciles_restored_hybrid_substrate(self):
        start = UPDATE.index("rollback() {")
        rollback = UPDATE[start:]

        self.assertIn(
            'RESTORED_HYBRID_INSTALLER="${INSTALL_DIR}/installer/install_hybrid_runtime_substrate.sh"',
            rollback,
        )
        self.assertIn(
            'RESTORED_HYBRID_CONFIG="${INSTALL_DIR}/runtime/hybrid-agent-state/agent.json"',
            rollback,
        )
        self.assertIn(
            'DSM_ROOT="${INSTALL_DIR}" bash "${RESTORED_HYBRID_INSTALLER}"',
            rollback,
        )

        reconcile = rollback.index(
            'DSM_ROOT="${INSTALL_DIR}" bash "${RESTORED_HYBRID_INSTALLER}"'
        )
        daemon_reload = rollback.index("systemctl daemon-reload", reconcile)

        self.assertLess(reconcile, daemon_reload)

    def test_homologation_checks_hybrid_substrate(self):
        homologation = (
            ROOT / "tests" / "test_server_update_homologation.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "assert_hybrid_substrate_ready()",
            homologation,
        )
        self.assertIn(
            "dsm-hybrid-agent-files-access@.service",
            homologation,
        )
        self.assertIn(
            "dsm-hybrid-agent-files-access@",
            homologation,
        )
        self.assertIn(
            "capivara-agent",
            homologation,
        )

        success_health = homologation.index(
            "capture_dsm_health after-success"
        )
        success_assert = homologation.index(
            "assert_hybrid_substrate_ready",
            success_health,
        )

        rollback_health = homologation.index(
            "capture_dsm_health after-rollback"
        )
        rollback_assert = homologation.index(
            "assert_hybrid_substrate_ready",
            rollback_health,
        )

        self.assertLess(success_health, success_assert)
        self.assertLess(rollback_health, rollback_assert)


if __name__ == "__main__":
    unittest.main()
