#!/usr/bin/env python3
"""Native E2E proof for Capivara-managed Windows Firewall rules.

Executed only on a Windows GitHub-hosted runner. The test invokes the production
managed_firewall module and independently queries NetSecurity to prove actual
OS rule creation, exposure filtering, idempotence, cleanup, and instance
ownership isolation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_RUNTIME = ROOT / "agents" / "windows" / "runtime"
sys.path.insert(0, str(WINDOWS_RUNTIME))

import managed_firewall  # noqa: E402


GROUP = "Capivara Managed Game Firewall"


def _instance_id(label: str) -> str:
    run_id = "".join(ch for ch in os.environ.get("GITHUB_RUN_ID", "local") if ch.isalnum())
    attempt = "".join(ch for ch in os.environ.get("GITHUB_RUN_ATTEMPT", "1") if ch.isalnum())
    return f"ci-native-fw-{label}-{run_id or 'local'}-{attempt or '1'}"


def _spec(instance_id: str, base_port: int) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "catalog_runtime_policy": {
            "network_exposure": [
                {"name": "game", "protocol": "udp", "exposure": "public"},
                {"name": "rcon", "protocol": "tcp", "exposure": "public"},
                {"name": "admin", "protocol": "tcp", "exposure": "private"},
            ]
        },
        "ports": {
            "game": {"port": base_port, "protocol": "udp"},
            "rcon": {"port": base_port + 1, "protocol": "tcp"},
            "admin": {"port": base_port + 2, "protocol": "tcp"},
        },
    }


def _powershell_json(script: str) -> Any:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "PowerShell query failed")
    text = completed.stdout.strip()
    return json.loads(text) if text else []


def _inventory(instance_id: str) -> list[dict[str, Any]]:
    prefix = f"Capivara:{instance_id}:"
    script = (
        "$ErrorActionPreference='Stop';"
        f"$group={json.dumps(GROUP)};"
        f"$prefix={json.dumps(prefix)};"
        "$rules=@(Get-NetFirewallRule -Group $group -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DisplayName -like ($prefix + '*') });"
        "$items=@(foreach($rule in $rules){"
        "$port=$rule | Get-NetFirewallPortFilter;"
        "[pscustomobject]@{"
        "DisplayName=$rule.DisplayName;"
        "Name=$rule.Name;"
        "Direction=$rule.Direction.ToString();"
        "Action=$rule.Action.ToString();"
        "Enabled=$rule.Enabled.ToString();"
        "Protocol=$port.Protocol.ToString();"
        "LocalPort=(@($port.LocalPort) -join ',')"
        "}"
        "});"
        "@($items) | ConvertTo-Json -Compress"
    )
    value = _powershell_json(script)
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise AssertionError(f"invalid Windows Firewall inventory: {value!r}")
    return [item for item in value if isinstance(item, dict)]


def _normalized_protocol(value: Any) -> str:
    text = str(value or "").strip().upper()
    return {"6": "TCP", "17": "UDP"}.get(text, text)


def _assert_expected_rules(instance_id: str, base_port: int) -> list[dict[str, Any]]:
    items = _inventory(instance_id)
    if len(items) != 2:
        raise AssertionError(f"expected exactly two Windows Firewall rules, got {items!r}")

    expected = {
        f"Capivara:{instance_id}:game:udp:{base_port}": ("UDP", str(base_port)),
        f"Capivara:{instance_id}:rcon:tcp:{base_port + 1}": ("TCP", str(base_port + 1)),
    }
    actual = {}
    for item in items:
        display_name = str(item.get("DisplayName") or "")
        protocol = _normalized_protocol(item.get("Protocol"))
        local_port = str(item.get("LocalPort") or "")
        actual[display_name] = (protocol, local_port)
        if str(item.get("Direction") or "").lower() != "inbound":
            raise AssertionError(f"rule is not inbound: {item!r}")
        if str(item.get("Action") or "").lower() != "allow":
            raise AssertionError(f"rule is not allow: {item!r}")
        if str(item.get("Enabled") or "").lower() not in {"true", "1"}:
            raise AssertionError(f"rule is not enabled: {item!r}")

    if actual != expected:
        raise AssertionError(f"unexpected native Windows Firewall rules: {actual!r}")
    if any(f":admin:tcp:{base_port + 2}" in name for name in actual):
        raise AssertionError("private catalog exposure was opened in Windows Firewall")
    return items


def main() -> int:
    instance_a = _instance_id("a")
    instance_b = _instance_id("b")
    spec_a = _spec(instance_a, 40110)
    spec_b = _spec(instance_b, 40210)

    # Instance-scoped cleanup makes reruns safe without touching unrelated rules.
    managed_firewall.remove(spec_a)
    managed_firewall.remove(spec_b)

    try:
        first_a = managed_firewall.reconcile(spec_a)
        first_b = managed_firewall.reconcile(spec_b)
        if first_a.get("backend") != "windows-firewall" or not first_a.get("changed"):
            raise AssertionError(f"first A reconcile did not create native rules: {first_a!r}")
        if first_b.get("backend") != "windows-firewall" or not first_b.get("changed"):
            raise AssertionError(f"first B reconcile did not create native rules: {first_b!r}")

        a_before = _assert_expected_rules(instance_a, 40110)
        b_before = _assert_expected_rules(instance_b, 40210)

        second_a = managed_firewall.reconcile(spec_a)
        if second_a.get("changed"):
            raise AssertionError(f"second A reconcile was not idempotent: {second_a!r}")
        if _inventory(instance_a) != a_before:
            raise AssertionError("second A reconcile changed native Windows Firewall inventory")
        if _inventory(instance_b) != b_before:
            raise AssertionError("reconciling A modified B rules")

        removed_a = managed_firewall.remove(spec_a)
        if not removed_a.get("changed"):
            raise AssertionError(f"first A remove reported no change: {removed_a!r}")
        if _inventory(instance_a):
            raise AssertionError("A rules remain after native Windows Firewall remove")
        if _inventory(instance_b) != b_before:
            raise AssertionError("removing A modified B rules")

        removed_a_again = managed_firewall.remove(spec_a)
        if removed_a_again.get("changed"):
            raise AssertionError(f"second A remove was not idempotent: {removed_a_again!r}")
        if _inventory(instance_b) != b_before:
            raise AssertionError("idempotent A remove modified B rules")

        print("native Windows Firewall E2E: PASS")
        print(f"instance A: {instance_a}")
        print(f"instance B: {instance_b}")
        print("proved: public exposure, protocol/port, idempotence, removal, cross-instance isolation")
        return 0
    finally:
        cleanup_errors = []
        for spec in (spec_a, spec_b):
            try:
                managed_firewall.remove(spec)
            except Exception as exc:  # cleanup must try both instances
                cleanup_errors.append(str(exc))
        if cleanup_errors and sys.exc_info()[0] is None:
            raise RuntimeError("; ".join(cleanup_errors))


if __name__ == "__main__":
    raise SystemExit(main())
