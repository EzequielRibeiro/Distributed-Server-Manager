#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
sys.path.insert(0, str(RUNTIME))

import instance_runtime
import privileged_firewall
import privileged_materialization


def test_remove_stops_runtime_before_firewall_and_materializer():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_state = instance_runtime.STATE_DIR
        old_instances = instance_runtime.INSTANCE_DIR
        old_resolve = privileged_materialization.resolve_adapter
        old_invoke = privileged_materialization._invoke
        old_firewall_remove = privileged_firewall.remove

        instance_runtime.STATE_DIR = root
        instance_runtime.INSTANCE_DIR = root / "instances"

        calls = []

        class Adapter:
            def status(self, spec):
                calls.append("status")
                return {"running": True}

            def stop(self, spec):
                calls.append("stop")
                return {"changed": True}

        spec = {
            "instance_id": "instance-one",
            "agent_id": "agent-one",
            "runtime_id": "runtime-one",
            "adapter": "systemd",
            "working_directory": str(root),
            "executable": "/bin/true",
            "desired_state": "running",
            "ports": {
                "game": {"port": 24000, "protocol": "udp"},
            },
            "catalog_runtime_policy": {
                "network_exposure": [
                    {"name": "game", "protocol": "udp", "exposure": "public"},
                ],
            },
        }

        instance_runtime.register_instance(spec)

        try:
            privileged_materialization.resolve_adapter = lambda value: Adapter()

            privileged_firewall.remove = lambda value: (
                calls.append("firewall")
                or {"backend": "ufw", "changed": True, "rules": []}
            )

            # privileged_materialization imports remove locally.
            sys.modules["privileged_firewall"].remove = privileged_firewall.remove

            privileged_materialization._invoke = lambda action, value, **extra: (
                calls.append("materializer")
                or {"changed": True}
            )

            result = privileged_materialization.remove(
                {"agent_id": "agent-one"},
                "instance-one",
            )

            assert calls == ["status", "stop", "firewall", "materializer"]
            assert result["firewall"]["backend"] == "ufw"
            assert instance_runtime.get_instance("instance-one") is None
        finally:
            privileged_materialization.resolve_adapter = old_resolve
            privileged_materialization._invoke = old_invoke
            privileged_firewall.remove = old_firewall_remove
            instance_runtime.STATE_DIR = old_state
            instance_runtime.INSTANCE_DIR = old_instances
