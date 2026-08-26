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
