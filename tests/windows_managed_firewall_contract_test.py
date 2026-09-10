from pathlib import Path
import importlib.util
import json


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "agents" / "windows" / "runtime" / "catalog_runtime_policy.py"


def _load():
    spec = importlib.util.spec_from_file_location(
        "windows_catalog_runtime_policy",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module



def _load_firewall():
    module_path = (
        ROOT
        / "agents"
        / "windows"
        / "runtime"
        / "managed_firewall.py"
    )
    spec = importlib.util.spec_from_file_location(
        "windows_managed_firewall",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _runtime_spec():
    return {
        "instance_id": "win-instance-001",
        "ports": {
            "game": {
                "port": 2302,
                "protocol": "udp",
            },
            "rcon": {
                "port": 2305,
                "protocol": "tcp",
            },
        },
        "catalog_runtime_policy": {
            "network_exposure": [
                {
                    "name": "game",
                    "protocol": "udp",
                    "exposure": "public",
                },
                {
                    "name": "rcon",
                    "protocol": "tcp",
                    "exposure": "none",
                },
            ]
        },
    }


def test_catalog_network_exposure_survives_windows_policy_application(tmp_path):
    module = _load()

    executable = tmp_path / "server.exe"
    executable.write_bytes(b"")

    instance = {
        "instance_id": "win-firewall-test",
        "game_id": "example",
    }

    spec = {
        "executable": str(executable),
        "working_directory": str(tmp_path),
        "arguments": [],
        "environment": {},
    }

    context = {
        "content_root": str(tmp_path),
        "catalog_runtime_policy": {
            "runtime_id": "example",
            "network_exposure": [
                {
                    "name": "game",
                    "protocol": "udp",
                    "exposure": "public",
                },
                {
                    "name": "rcon",
                    "protocol": "tcp",
                    "exposure": "none",
                },
            ],
        },
    }

    result = module.apply_policy(spec, instance, context)

    assert result["catalog_runtime_policy"]["network_exposure"] == [
        {
            "name": "game",
            "protocol": "udp",
            "exposure": "public",
        },
        {
            "name": "rcon",
            "protocol": "tcp",
            "exposure": "none",
        },
    ]


def test_windows_runtime_materialization_uses_managed_firewall():
    source = (
        ROOT
        / "agents"
        / "windows"
        / "runtime"
        / "runtime_materialization.py"
    ).read_text(encoding="utf-8")

    assert "import managed_firewall" in source

    assert (
        "firewall=managed_firewall.reconcile(normalized)"
        in source
    )

    assert (
        "firewall=managed_firewall.remove(normalized)"
        in source
    )


def test_windows_firewall_is_reconciled_before_runtime_start():
    source = (
        ROOT
        / "agents"
        / "windows"
        / "runtime"
        / "runtime_materialization.py"
    ).read_text(encoding="utf-8")

    firewall = source.index(
        "firewall=managed_firewall.reconcile(normalized)"
    )

    adapter = source.index(
        "adapter=resolve_adapter(normalized)",
        firewall,
    )

    lifecycle = source.index(
        'if desired=="running"',
        adapter,
    )

    assert firewall < adapter < lifecycle


def test_windows_firewall_is_removed_before_instance_record():
    source = (
        ROOT
        / "agents"
        / "windows"
        / "runtime"
        / "runtime_materialization.py"
    ).read_text(encoding="utf-8")

    remove = source.index(
        "firewall=managed_firewall.remove(normalized)"
    )

    unlink = source.index(
        "instance_runtime._instance_path(instance_id).unlink()",
        remove,
    )

    assert remove < unlink


def test_windows_managed_firewall_adds_public_rule_only():
    fw = _load_firewall()
    calls = []

    def runner(command, timeout):
        calls.append(command)
        joined = " ".join(command)

        if "Get-NetFirewallRule" in joined:
            return 0, "[]", ""

        if "New-NetFirewallRule" in joined:
            return 0, "", ""

        raise AssertionError(joined)

    result = fw.reconcile(
        _runtime_spec(),
        runner=runner,
    )

    assert result["backend"] == "windows-firewall"
    assert result["changed"] is True

    create = [
        command
        for command in calls
        if "New-NetFirewallRule" in " ".join(command)
    ]

    assert len(create) == 1

    command = " ".join(create[0])

    assert "2302" in command
    assert "UDP" in command
    assert "2305" not in command


def test_windows_managed_firewall_is_idempotent():
    fw = _load_firewall()

    existing = [{
        "DisplayName":
            "Capivara:win-instance-001:game:udp:2302",
        "Name": "capivara-rule-guid",
    }]

    calls = []

    def runner(command, timeout):
        calls.append(command)
        joined = " ".join(command)

        if "Get-NetFirewallRule" in joined:
            return 0, json.dumps(existing), ""

        raise AssertionError(
            f"unexpected mutation: {joined}"
        )

    result = fw.reconcile(
        _runtime_spec(),
        runner=runner,
    )

    assert result["changed"] is False
    assert len(calls) == 1


def test_windows_managed_firewall_removes_stale_owned_rule():
    fw = _load_firewall()

    existing = [{
        "DisplayName":
            "Capivara:win-instance-001:old:tcp:9999",
        "Name": "old-capivara-rule",
    }]

    calls = []

    def runner(command, timeout):
        calls.append(command)
        joined = " ".join(command)

        if "Get-NetFirewallRule" in joined:
            return 0, json.dumps(existing), ""

        if "Remove-NetFirewallRule" in joined:
            return 0, "", ""

        if "New-NetFirewallRule" in joined:
            return 0, "", ""

        raise AssertionError(joined)

    result = fw.reconcile(
        _runtime_spec(),
        runner=runner,
    )

    assert result["changed"] is True

    removed = [
        command
        for command in calls
        if "Remove-NetFirewallRule" in " ".join(command)
    ]

    assert len(removed) == 1
    assert "old-capivara-rule" in " ".join(removed[0])


def test_windows_managed_firewall_rejects_protocol_mismatch():
    fw = _load_firewall()

    spec = _runtime_spec()
    spec["ports"]["game"]["protocol"] = "tcp"

    try:
        fw.public_rules(spec)
    except ValueError as exc:
        assert "protocol mismatch" in str(exc)
    else:
        raise AssertionError(
            "protocol mismatch must fail closed"
        )


def test_windows_legacy_runtime_without_catalog_policy_is_unmanaged_noop():
    fw = _load_firewall()

    calls = []

    def runner(command, timeout):
        calls.append(command)
        raise AssertionError("legacy runtime must not invoke Windows Firewall")

    result = fw.reconcile(
        {
            "instance_id": "legacy-instance",
            "ports": {},
        },
        runner=runner,
    )

    assert result == {
        "backend": "windows-firewall",
        "changed": False,
        "rules": [],
        "managed": False,
    }
    assert calls == []


def test_windows_catalog_runtime_without_exposure_still_fails_closed():
    fw = _load_firewall()

    spec = {
        "instance_id": "catalog-instance",
        "ports": {
            "game": {
                "port": 2302,
                "protocol": "udp",
            }
        },
        "catalog_runtime_policy": {
            "runtime_id": "dayz",
        },
    }

    try:
        fw.reconcile(spec, runner=lambda *_: (0, "[]", ""))
    except ValueError as exc:
        assert "network exposure" in str(exc)
    else:
        raise AssertionError(
            "catalog-managed runtime without exposure must fail closed"
        )
