#!/usr/bin/env python3
"""Native E2E proof for Capivara-managed Linux UFW rules.

This test is intentionally executed only by the privileged native-firewall
GitHub Actions job. It uses the production catalog exposure resolver and the
production root-owned UFW reconciler, then inspects UFW independently to prove
idempotence and instance ownership isolation.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LINUX_RUNTIME = ROOT / "agents" / "linux" / "runtime"
LINUX_PRIVILEGED = ROOT / "agents" / "linux" / "privileged" / "reconcile_firewall.py"

sys.path.insert(0, str(LINUX_RUNTIME))
import privileged_firewall  # noqa: E402


def _load_reconciler():
    spec = importlib.util.spec_from_file_location(
        "capivara_native_reconcile_firewall",
        LINUX_PRIVILEGED,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Linux privileged firewall reconciler")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reconciler = _load_reconciler()


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


def _ufw_output() -> str:
    completed = subprocess.run(
        ["ufw", "status", "numbered"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "ufw status failed")
    return completed.stdout


def _owned_lines(instance_id: str) -> list[str]:
    marker = f"# capivara:{instance_id}:"
    return [line.strip() for line in _ufw_output().splitlines() if marker in line]


def _assert_expected_rules(instance_id: str, base_port: int) -> list[str]:
    lines = _owned_lines(instance_id)
    if not lines:
        raise AssertionError(f"no native UFW rules found for {instance_id}")

    text = "\n".join(lines)
    expected = {
        f"capivara:{instance_id}:game:udp:{base_port}",
        f"capivara:{instance_id}:rcon:tcp:{base_port + 1}",
    }
    for comment in expected:
        if comment not in text:
            raise AssertionError(f"missing native UFW rule comment: {comment}\n{text}")

    private_comment = f"capivara:{instance_id}:admin:tcp:{base_port + 2}"
    if private_comment in text:
        raise AssertionError("private catalog exposure was opened in UFW")

    return lines


def main() -> int:
    instance_a = _instance_id("a")
    instance_b = _instance_id("b")
    spec_a = _spec(instance_a, 40110)
    spec_b = _spec(instance_b, 40210)
    desired_a = privileged_firewall.public_rules(spec_a)
    desired_b = privileged_firewall.public_rules(spec_b)

    if {(rule["name"], rule["protocol"], rule["port"]) for rule in desired_a} != {
        ("game", "udp", 40110),
        ("rcon", "tcp", 40111),
    }:
        raise AssertionError(f"unexpected resolved exposure for A: {desired_a!r}")

    # Start from a clean instance-owned state without touching unrelated rules.
    reconciler.reconcile_ufw(instance_a, [])
    reconciler.reconcile_ufw(instance_b, [])

    try:
        first_a = reconciler.reconcile_ufw(instance_a, desired_a)
        first_b = reconciler.reconcile_ufw(instance_b, desired_b)
        if first_a.get("backend") != "ufw" or not first_a.get("changed"):
            raise AssertionError(f"first A reconcile did not create native rules: {first_a!r}")
        if first_b.get("backend") != "ufw" or not first_b.get("changed"):
            raise AssertionError(f"first B reconcile did not create native rules: {first_b!r}")

        a_before = _assert_expected_rules(instance_a, 40110)
        b_before = _assert_expected_rules(instance_b, 40210)

        second_a = reconciler.reconcile_ufw(instance_a, desired_a)
        if second_a.get("changed"):
            raise AssertionError(f"second A reconcile was not idempotent: {second_a!r}")
        if _owned_lines(instance_a) != a_before:
            raise AssertionError("second A reconcile changed native UFW inventory")
        if _owned_lines(instance_b) != b_before:
            raise AssertionError("reconciling A modified B rules")

        removed_a = reconciler.reconcile_ufw(instance_a, [])
        if not removed_a.get("changed"):
            raise AssertionError(f"first A remove reported no change: {removed_a!r}")
        if _owned_lines(instance_a):
            raise AssertionError("A rules remain after native UFW remove")
        if _owned_lines(instance_b) != b_before:
            raise AssertionError("removing A modified B rules")

        removed_a_again = reconciler.reconcile_ufw(instance_a, [])
        if removed_a_again.get("changed"):
            raise AssertionError(f"second A remove was not idempotent: {removed_a_again!r}")
        if _owned_lines(instance_b) != b_before:
            raise AssertionError("idempotent A remove modified B rules")

        print("native Linux UFW E2E: PASS")
        print(f"instance A: {instance_a}")
        print(f"instance B: {instance_b}")
        print("proved: public exposure, protocol/port, idempotence, removal, cross-instance isolation")
        return 0
    finally:
        # Cleanup is instance-scoped. Never reset the host firewall from Python.
        try:
            reconciler.reconcile_ufw(instance_a, [])
        finally:
            reconciler.reconcile_ufw(instance_b, [])


if __name__ == "__main__":
    raise SystemExit(main())
