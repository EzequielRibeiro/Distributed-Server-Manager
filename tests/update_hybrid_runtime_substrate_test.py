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


if __name__ == "__main__":
    unittest.main()
