from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"

for path in (str(ROOT), str(DATABASE)):
    if path not in sys.path:
        sys.path.insert(0, path)


def test_contract_create_does_not_load_delete_runtime_dependency():
    sys.modules.pop("contract_cli", None)
    sys.modules.pop("agent_instance_runtime_repository", None)

    module = importlib.import_module("contract_cli")

    assert "agent_instance_runtime_repository" not in sys.modules
    args = module.build_parser().parse_args(
        ["create", "--customer", "1", "--game", "dayz"]
    )
    assert args.action == "create"
    assert args.customer == "1"
    assert args.game == "dayz"


def test_customer_create_uses_database_generated_identifier():
    sys.modules.pop("customer_cli", None)
    module = importlib.import_module("customer_cli")

    args = module.build_parser().parse_args(
        ["create", "--name", "Aurora", "--username", "aurora"]
    )

    assert args.action == "create"
    assert args.name == "Aurora"
    assert args.username == "aurora"
    assert not hasattr(args, "customer_id")


def test_public_cap_help_matches_generated_customer_identifier_contract():
    cap = (ROOT / "bin" / "cap").read_text(encoding="utf-8")

    assert (
        "cap customer create --name NOME --username LOGIN "
        "[--controller ID] [--email EMAIL] [--phone TELEFONE]"
    ) in cap
    assert "cap customer create --id ID" not in cap


def test_database_migrate_returns_nonzero_when_postcondition_is_invalid(monkeypatch):
    manager = importlib.import_module("manager")
    monkeypatch.setattr(
        manager,
        "execute_backend_command",
        lambda args: {
            "kind": "DatabaseCheck",
            "initialized": True,
            "valid": False,
        },
    )

    assert manager.main(["migrate"]) == 1


def test_database_migrate_returns_zero_when_postcondition_is_valid(monkeypatch):
    manager = importlib.import_module("manager")
    monkeypatch.setattr(
        manager,
        "execute_backend_command",
        lambda args: {
            "kind": "DatabaseCheck",
            "initialized": True,
            "valid": True,
        },
    )

    assert manager.main(["migrate"]) == 0


def test_update_preflight_uses_target_manager_before_update_transaction():
    update = (ROOT / "update.sh").read_text(encoding="utf-8")
    guard = (ROOT / "update-manager" / "process-guard.sh").read_text(
        encoding="utf-8"
    )

    assert "process_guard_assert_target_database_compatible" in guard
    assert 'manager="${target_root}/database/manager.py"' in guard
    assert 'python3 "${manager}" --root "${install_root}" check' in guard

    gate_start = guard.index("process_guard_pre_update()")
    database_gate = guard.index(
        "process_guard_assert_target_database_compatible", gate_start
    )
    runtime_gate = guard.index("process_guard_assert_no_active_instances", gate_start)
    assert database_gate < runtime_gate

    main_start = update.index("main()")
    process_guard = update.index("run_process_guard", main_start)
    transaction_start = update.index("UPDATE_TRANSACTION_STARTED=1", main_start)
    stop_services = update.index("stop_services", transaction_start)

    assert process_guard < transaction_start < stop_services
