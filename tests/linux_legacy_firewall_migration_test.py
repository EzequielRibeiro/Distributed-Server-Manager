#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "agents" / "linux" / "privileged" / "reconcile_firewall.py"
spec = importlib.util.spec_from_file_location("reconcile_firewall_legacy", MODULE)
assert spec and spec.loader
firewall = importlib.util.module_from_spec(spec)
spec.loader.exec_module(firewall)


class FakeRunner:
    def __init__(self, numbered: str) -> None:
        self.numbered = numbered
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], timeout: int):
        self.commands.append(list(command))
        if command == ["ufw", "status"]:
            return 0, "Status: active\n", ""
        if command == ["ufw", "status", "numbered"]:
            return 0, self.numbered, ""
        return 0, "ok\n", ""


def desired_dayz(instance_id: str = "cli-000001-dayz-001"):
    return firewall._validate_rules(
        instance_id,
        [
            {"name": "game", "protocol": "udp", "port": 24000},
            {"name": "game_aux", "protocol": "udp", "port": 24002},
            {"name": "steam_query", "protocol": "udp", "port": 24003},
        ],
    )


def test_migrates_real_legacy_dayz_rules_to_owned_comments() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[54] 24000/udp ALLOW IN Anywhere # Capivara DayZ game\n"
        "[55] 24002/udp ALLOW IN Anywhere # Capivara DayZ game aux\n"
        "[56] 24003/udp ALLOW IN Anywhere # Capivara DayZ Steam query\n"
    )

    result = firewall.reconcile_ufw(
        "cli-000001-dayz-001",
        desired_dayz(),
        runner,
    )

    assert result["changed"] is True
    assert ["ufw", "--force", "delete", "56"] in runner.commands
    assert ["ufw", "--force", "delete", "55"] in runner.commands
    assert ["ufw", "--force", "delete", "54"] in runner.commands
    assert [
        "ufw", "allow", "24000/udp", "comment",
        "capivara:cli-000001-dayz-001:game:udp:24000",
    ] in runner.commands
    assert [
        "ufw", "allow", "24002/udp", "comment",
        "capivara:cli-000001-dayz-001:game_aux:udp:24002",
    ] in runner.commands
    assert [
        "ufw", "allow", "24003/udp", "comment",
        "capivara:cli-000001-dayz-001:steam_query:udp:24003",
    ] in runner.commands


def test_never_migrates_external_rule_on_same_protocol_port() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[ 1] 24000/udp ALLOW IN Anywhere # administrator-manual-rule\n"
        "[ 2] 22/tcp ALLOW IN Anywhere # Capivara SSH historical\n"
    )

    firewall.reconcile_ufw(
        "cli-000001-dayz-001",
        firewall._validate_rules(
            "cli-000001-dayz-001",
            [{"name": "game", "protocol": "udp", "port": 24000}],
        ),
        runner,
    )

    assert ["ufw", "--force", "delete", "1"] not in runner.commands
    assert ["ufw", "--force", "delete", "2"] not in runner.commands
    assert [
        "ufw", "allow", "24000/udp", "comment",
        "capivara:cli-000001-dayz-001:game:udp:24000",
    ] in runner.commands


def test_canonical_rule_is_idempotent_after_migration() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[ 1] 24000/udp ALLOW IN Anywhere # capivara:cli-000001-dayz-001:game:udp:24000\n"
    )

    result = firewall.reconcile_ufw(
        "cli-000001-dayz-001",
        firewall._validate_rules(
            "cli-000001-dayz-001",
            [{"name": "game", "protocol": "udp", "port": 24000}],
        ),
        runner,
    )

    assert result["changed"] is False
    assert len(runner.commands) == 2


def test_remove_cleans_rule_after_migration() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[ 1] 24000/udp ALLOW IN Anywhere # capivara:cli-000001-dayz-001:game:udp:24000\n"
        "[ 2] 22/tcp ALLOW IN Anywhere # administrator-ssh\n"
    )

    result = firewall.reconcile_ufw("cli-000001-dayz-001", [], runner)

    assert result["changed"] is True
    assert ["ufw", "--force", "delete", "1"] in runner.commands
    assert ["ufw", "--force", "delete", "2"] not in runner.commands


def test_same_numeric_port_other_protocol_is_not_migrated() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[ 1] 24000/tcp ALLOW IN Anywhere # Capivara old tcp rule\n"
    )

    firewall.reconcile_ufw(
        "cli-000001-dayz-001",
        firewall._validate_rules(
            "cli-000001-dayz-001",
            [{"name": "game", "protocol": "udp", "port": 24000}],
        ),
        runner,
    )

    assert ["ufw", "--force", "delete", "1"] not in runner.commands


if __name__ == "__main__":
    test_migrates_real_legacy_dayz_rules_to_owned_comments()
    test_never_migrates_external_rule_on_same_protocol_port()
    test_canonical_rule_is_idempotent_after_migration()
    test_remove_cleans_rule_after_migration()
    test_same_numeric_port_other_protocol_is_not_migrated()
    print("linux legacy firewall migration: OK")
