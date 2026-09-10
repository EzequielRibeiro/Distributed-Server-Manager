#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "agents" / "linux" / "privileged" / "reconcile_firewall.py"
spec = importlib.util.spec_from_file_location("reconcile_firewall", MODULE)
assert spec and spec.loader
firewall = importlib.util.module_from_spec(spec)
spec.loader.exec_module(firewall)


class FakeRunner:
    def __init__(self, numbered: str = "Status: active\n") -> None:
        self.numbered = numbered
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], timeout: int):
        self.commands.append(list(command))
        if command == ["ufw", "status"]:
            return 0, "Status: active\n", ""
        if command == ["ufw", "status", "numbered"]:
            return 0, self.numbered, ""
        return 0, "ok\n", ""


def test_adds_only_explicit_desired_rule_with_owned_comment() -> None:
    runner = FakeRunner()
    result = firewall.reconcile_ufw(
        "instance-1",
        firewall._validate_rules("instance-1", [{"name": "game", "protocol": "udp", "port": 24010}]),
        runner,
    )
    assert result["backend"] == "ufw"
    assert ["ufw", "allow", "24010/udp", "comment", "capivara:instance-1:game:udp:24010"] in runner.commands
    assert not any(command[:3] == ["ufw", "--force", "delete"] for command in runner.commands)


def test_existing_owned_rule_is_idempotent() -> None:
    runner = FakeRunner("Status: active\n[ 1] 24010/udp ALLOW IN Anywhere # capivara:instance-1:game:udp:24010\n")
    desired = firewall._validate_rules("instance-1", [{"name": "game", "protocol": "udp", "port": 24010}])
    result = firewall.reconcile_ufw("instance-1", desired, runner)
    assert result["changed"] is False
    assert len(runner.commands) == 2


def test_removes_only_stale_rules_owned_by_same_instance() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[ 1] 22/tcp ALLOW IN Anywhere # administrator-ssh\n"
        "[ 2] 24010/udp ALLOW IN Anywhere # capivara:instance-1:game:udp:24010\n"
        "[ 3] 25000/udp ALLOW IN Anywhere # capivara:other:game:udp:25000\n"
    )
    result = firewall.reconcile_ufw("instance-1", [], runner)
    assert result["changed"] is True
    assert ["ufw", "--force", "delete", "2"] in runner.commands
    assert ["ufw", "--force", "delete", "1"] not in runner.commands
    assert ["ufw", "--force", "delete", "3"] not in runner.commands


def test_inactive_backend_fails_closed_when_public_rule_is_required() -> None:
    def inactive(command: list[str], timeout: int):
        if command == ["ufw", "status"]:
            return 0, "Status: inactive\n", ""
        return 1, "", "unexpected"
    desired = firewall._validate_rules("instance-1", [{"name": "game", "protocol": "tcp", "port": 25565}])
    try:
        firewall.reconcile_ufw("instance-1", desired, inactive)
    except RuntimeError as exc:
        assert "UFW is not active" in str(exc)
    else:
        raise AssertionError("required public rule must fail closed without an active backend")


def test_rule_validation_rejects_injection_and_invalid_protocol() -> None:
    for rule in (
        {"name": "game;ufw-reset", "protocol": "udp", "port": 24010},
        {"name": "game", "protocol": "udp;delete", "port": 24010},
        {"name": "game", "protocol": "udp", "port": "24010\nallow 22"},
    ):
        try:
            firewall._validate_rules("instance-1", [rule])
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError(f"unsafe firewall rule accepted: {rule!r}")


if __name__ == "__main__":
    test_adds_only_explicit_desired_rule_with_owned_comment()
    test_existing_owned_rule_is_idempotent()
    test_removes_only_stale_rules_owned_by_same_instance()
    test_inactive_backend_fails_closed_when_public_rule_is_required()
    test_rule_validation_rejects_injection_and_invalid_protocol()
    print("linux managed firewall: OK")
