from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"

for path in (str(ROOT), str(DATABASE)):
    if path not in sys.path:
        sys.path.insert(0, path)


class V208DatabaseAndAdminCliRegressionTest(unittest.TestCase):
    def test_contract_create_does_not_load_delete_runtime_dependency(self):
        sys.modules.pop("contract_cli", None)
        sys.modules.pop("agent_instance_runtime_repository", None)

        module = importlib.import_module("contract_cli")

        self.assertNotIn("agent_instance_runtime_repository", sys.modules)
        args = module.build_parser().parse_args(
            ["create", "--customer", "1", "--game", "dayz"]
        )
        self.assertEqual(args.action, "create")
        self.assertEqual(args.customer, "1")
        self.assertEqual(args.game, "dayz")

    def test_customer_create_uses_database_generated_identifier(self):
        sys.modules.pop("customer_cli", None)
        module = importlib.import_module("customer_cli")

        args = module.build_parser().parse_args(
            ["create", "--name", "Aurora", "--username", "aurora"]
        )

        self.assertEqual(args.action, "create")
        self.assertEqual(args.name, "Aurora")
        self.assertEqual(args.username, "aurora")
        self.assertFalse(hasattr(args, "customer_id"))

    def test_public_cap_help_matches_generated_customer_identifier_contract(self):
        cap = (ROOT / "bin" / "cap").read_text(encoding="utf-8")

        self.assertIn(
            "cap customer create --name NOME --username LOGIN "
            "[--controller ID] [--email EMAIL] [--phone TELEFONE]",
            cap,
        )
        self.assertNotIn("cap customer create --id ID", cap)

    def test_database_migrate_returns_nonzero_when_postcondition_is_invalid(self):
        manager = importlib.import_module("manager")
        payload = {
            "kind": "DatabaseCheck",
            "initialized": True,
            "valid": False,
        }
        with mock.patch.object(manager, "execute_backend_command", return_value=payload):
            self.assertEqual(manager.main(["migrate"]), 1)

    def test_database_migrate_returns_zero_when_postcondition_is_valid(self):
        manager = importlib.import_module("manager")
        payload = {
            "kind": "DatabaseCheck",
            "initialized": True,
            "valid": True,
        }
        with mock.patch.object(manager, "execute_backend_command", return_value=payload):
            self.assertEqual(manager.main(["migrate"]), 0)

    def test_update_preflight_uses_target_manager_before_update_transaction(self):
        update = (ROOT / "update.sh").read_text(encoding="utf-8")
        guard = (ROOT / "update-manager" / "process-guard.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("process_guard_assert_target_database_compatible", guard)
        self.assertIn('manager="${target_root}/database/manager.py"', guard)
        self.assertIn('python3 "${manager}" --root "${install_root}" check', guard)

        gate_start = guard.index("process_guard_pre_update()")
        database_gate = guard.index(
            "process_guard_assert_target_database_compatible", gate_start
        )
        runtime_gate = guard.index("process_guard_assert_no_active_instances", gate_start)
        self.assertLess(database_gate, runtime_gate)

        main_start = update.index("main()")
        process_guard = update.index("run_process_guard", main_start)
        transaction_start = update.index("UPDATE_TRANSACTION_STARTED=1", main_start)
        stop_services = update.index("stop_services", transaction_start)
        self.assertLess(process_guard, transaction_start)
        self.assertLess(transaction_start, stop_services)


if __name__ == "__main__":
    unittest.main()
