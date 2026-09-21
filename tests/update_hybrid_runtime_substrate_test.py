#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPDATE = (ROOT / "update.sh").read_text(encoding="utf-8")
INSTALLER = (
    ROOT / "installer" / "install_hybrid_runtime_substrate.sh"
).read_text(encoding="utf-8")


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
            'DSM_ROOT="${INSTALL_DIR}" bash "${INSTALLER}"',
            UPDATE,
        )

    def test_native_command_substrate_is_installed(self):
        self.assertIn(
            "dsm-hybrid-agent-native-command@.service",
            INSTALLER,
        )
        self.assertIn(
            "CAPIVARA_NATIVE_COMMAND_UNIT_TEMPLATE",
            INSTALLER,
        )
        self.assertIn(
            "privileged-native-command",
            INSTALLER,
        )
        self.assertIn(
            "dsm-hybrid-agent-native-command@",
            INSTALLER,
        )

    def test_reconcile_runs_after_systemd_and_before_restart(self):
        main_start = UPDATE.index("main() {")
        main = UPDATE[main_start:]

        update_systemd = main.index(
            "    update_systemd"
        )
        reconcile = main.index(
            "    reconcile_hybrid_runtime_substrate"
        )
        restart = main.index(
            "    restart_services"
        )

        self.assertLess(
            update_systemd,
            reconcile,
        )
        self.assertLess(
            reconcile,
            restart,
        )

    def test_non_hybrid_installations_are_skipped(self):
        start = UPDATE.index(
            "reconcile_hybrid_runtime_substrate()"
        )
        end = UPDATE.index(
            "# =============================================================\n"
            "# Reiniciar serviços DSM",
            start,
        )
        function = UPDATE[start:end]

        self.assertIn(
            'if [[ ! -f "${AGENT_CONFIG}" ]]',
            function,
        )
        self.assertIn(
            "return 0",
            function,
        )

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
        daemon_reload = rollback.index(
            "systemctl daemon-reload",
            reconcile,
        )

        self.assertLess(
            reconcile,
            daemon_reload,
        )


if __name__ == "__main__":
    unittest.main()
