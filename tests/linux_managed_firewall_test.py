#!/usr/bin/env python3
from __future__ import annotations

import json

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


def _desired_dayz(instance_id: str = "cli-000001-dayz-001"):
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
    result = firewall.reconcile_ufw("cli-000001-dayz-001", _desired_dayz(), runner)
    assert result["changed"] is True
    for number in (56, 55, 54):
        assert ["ufw", "--force", "delete", str(number)] in runner.commands
    assert ["ufw", "allow", "24000/udp", "comment", "capivara:cli-000001-dayz-001:game:udp:24000"] in runner.commands
    assert ["ufw", "allow", "24002/udp", "comment", "capivara:cli-000001-dayz-001:game_aux:udp:24002"] in runner.commands
    assert ["ufw", "allow", "24003/udp", "comment", "capivara:cli-000001-dayz-001:steam_query:udp:24003"] in runner.commands


def test_legacy_migration_never_removes_external_rule() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[ 1] 24000/udp ALLOW IN Anywhere # administrator-manual-rule\n"
        "[ 2] 22/tcp ALLOW IN Anywhere # Capivara SSH historical\n"
    )
    desired = firewall._validate_rules(
        "cli-000001-dayz-001",
        [{"name": "game", "protocol": "udp", "port": 24000}],
    )
    firewall.reconcile_ufw("cli-000001-dayz-001", desired, runner)
    assert ["ufw", "--force", "delete", "1"] not in runner.commands
    assert ["ufw", "--force", "delete", "2"] not in runner.commands
    assert ["ufw", "allow", "24000/udp", "comment", "capivara:cli-000001-dayz-001:game:udp:24000"] in runner.commands


def test_canonical_rule_is_idempotent_after_legacy_migration() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[ 1] 24000/udp ALLOW IN Anywhere # capivara:cli-000001-dayz-001:game:udp:24000\n"
    )
    desired = firewall._validate_rules(
        "cli-000001-dayz-001",
        [{"name": "game", "protocol": "udp", "port": 24000}],
    )
    result = firewall.reconcile_ufw("cli-000001-dayz-001", desired, runner)
    assert result["changed"] is False
    assert len(runner.commands) == 2


def test_remove_cleans_canonical_rule_after_legacy_migration() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[ 1] 24000/udp ALLOW IN Anywhere # capivara:cli-000001-dayz-001:game:udp:24000\n"
        "[ 2] 22/tcp ALLOW IN Anywhere # administrator-ssh\n"
    )
    result = firewall.reconcile_ufw("cli-000001-dayz-001", [], runner)
    assert result["changed"] is True
    assert ["ufw", "--force", "delete", "1"] in runner.commands
    assert ["ufw", "--force", "delete", "2"] not in runner.commands


def test_legacy_migration_requires_exact_protocol_match() -> None:
    runner = FakeRunner(
        "Status: active\n"
        "[ 1] 24000/tcp ALLOW IN Anywhere # Capivara old tcp rule\n"
    )
    desired = firewall._validate_rules(
        "cli-000001-dayz-001",
        [{"name": "game", "protocol": "udp", "port": 24000}],
    )
    firewall.reconcile_ufw("cli-000001-dayz-001", desired, runner)
    assert ["ufw", "--force", "delete", "1"] not in runner.commands


if __name__ == "__main__":
    test_adds_only_explicit_desired_rule_with_owned_comment()
    test_existing_owned_rule_is_idempotent()
    test_removes_only_stale_rules_owned_by_same_instance()
    test_inactive_backend_fails_closed_when_public_rule_is_required()
    test_rule_validation_rejects_injection_and_invalid_protocol()
    test_migrates_real_legacy_dayz_rules_to_owned_comments()
    test_legacy_migration_never_removes_external_rule()
    test_canonical_rule_is_idempotent_after_legacy_migration()
    test_remove_cleans_canonical_rule_after_legacy_migration()
    test_legacy_migration_requires_exact_protocol_match()
    print("linux managed firewall: OK")


def test_result_preserves_request_owner(tmp_path, monkeypatch):
    request_dir = tmp_path / "privileged-firewall"
    request_dir.mkdir()

    old_request_dir = firewall.REQUEST_DIR
    firewall.REQUEST_DIR = request_dir

    instance_id = "instance-owner"
    request_path = request_dir / f"{instance_id}.request.json"
    request_path.write_text(
        json.dumps(
            {
                "kind": "CapivaraPrivilegedFirewallRequest",
                "instance_id": instance_id,
                "rules": [],
            }
        ),
        encoding="utf-8",
    )
    request_path.chmod(0o600)

    expected_owner = (request_path.stat().st_uid, request_path.stat().st_gid)
    chowns = []

    def record_chown(path, uid, gid):
        chowns.append((Path(path), uid, gid))

    monkeypatch.setattr(firewall.os, "chown", record_chown)

    def runner(command, timeout):
        if command == ["ufw", "status"]:
            return 0, "Status: inactive\n", ""
        raise AssertionError(command)

    try:
        result = firewall.run(instance_id, runner)
    finally:
        firewall.REQUEST_DIR = old_request_dir

    assert result["status"] == "completed"
    assert chowns
    assert chowns[-1][1:] == expected_owner

    result_path = request_dir / f"{instance_id}.result.json"
    assert result_path.stat().st_uid == expected_owner[0]
    assert result_path.stat().st_gid == expected_owner[1]
    assert result_path.stat().st_mode & 0o777 == 0o600


def test_missing_request_returns_failed_result_without_stat_crash(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("CAPIVARA_AGENT_STATE_DIR", str(tmp_path))

    import agents.linux.privileged.reconcile_firewall as firewall_module

    reloaded = importlib.reload(firewall_module)
    result = reloaded.run("missing-instance")

    assert result["status"] == "failed"
    assert result["instance_id"] == "missing-instance"
    assert "No such file" in result["error"] or "not found" in result["error"].lower()

    result_path = tmp_path / "privileged-firewall" / "missing-instance.result.json"
    assert result_path.is_file()
