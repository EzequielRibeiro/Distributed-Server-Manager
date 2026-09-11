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


def _managed_spec(root: Path, *, desired_state: str = "running"):
    return {
        "instance_id": "instance-one",
        "agent_id": "agent-one",
        "runtime_id": "runtime-one",
        "adapter": "systemd",
        "working_directory": str(root),
        "executable": "/bin/true",
        "desired_state": desired_state,
        "observed_state": desired_state,
        "ports": {
            "game": {"port": 24000, "protocol": "udp"},
        },
        "catalog_runtime_policy": {
            "network_exposure": [
                {"name": "game", "protocol": "udp", "exposure": "public"},
            ],
        },
    }


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

        spec = _managed_spec(root)
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


def test_lifecycle_stop_cleans_firewall_even_when_adapter_stop_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_state = instance_runtime.STATE_DIR
        old_instances = instance_runtime.INSTANCE_DIR
        old_resolve = instance_runtime.resolve_adapter
        old_firewall_remove = privileged_firewall.remove

        instance_runtime.STATE_DIR = root
        instance_runtime.INSTANCE_DIR = root / "instances"
        calls = []

        class Adapter:
            name = "fake"

            def stop(self, spec):
                calls.append("stop")
                return {
                    "action": "stop",
                    "changed": False,
                    "idempotent": True,
                    "state": {
                        "available": True,
                        "active_state": "inactive",
                        "running": False,
                    },
                }

        instance_runtime.register_instance(_managed_spec(root, desired_state="stopped"))

        def remove_firewall(value):
            stored = instance_runtime.get_instance("instance-one")
            assert stored["desired_state"] == "stopped"
            assert stored["observed_state"] == "stopped"
            calls.append("firewall")
            return {"backend": "ufw", "changed": True, "rules": []}

        try:
            instance_runtime.resolve_adapter = lambda value: Adapter()
            privileged_firewall.remove = remove_firewall
            sys.modules["privileged_firewall"].remove = remove_firewall

            result = instance_runtime.lifecycle(
                {"agent_id": "agent-one"},
                "instance-one",
                "stop",
            )

            assert calls == ["stop", "firewall"]
            assert result["operation"]["idempotent"] is True
            assert result["observed_state"] == "stopped"
            assert result["firewall"] == {
                "backend": "ufw",
                "changed": True,
                "rules": [],
            }
        finally:
            instance_runtime.resolve_adapter = old_resolve
            privileged_firewall.remove = old_firewall_remove
            sys.modules["privileged_firewall"].remove = old_firewall_remove
            instance_runtime.STATE_DIR = old_state
            instance_runtime.INSTANCE_DIR = old_instances


def test_lifecycle_stop_keeps_stopped_state_when_firewall_teardown_fails():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_state = instance_runtime.STATE_DIR
        old_instances = instance_runtime.INSTANCE_DIR
        old_resolve = instance_runtime.resolve_adapter
        old_firewall_remove = privileged_firewall.remove

        instance_runtime.STATE_DIR = root
        instance_runtime.INSTANCE_DIR = root / "instances"
        calls = []

        class Adapter:
            name = "fake"

            def stop(self, spec):
                calls.append("stop")
                return {
                    "action": "stop",
                    "changed": True,
                    "state": {
                        "available": True,
                        "active_state": "inactive",
                        "running": False,
                    },
                }

        instance_runtime.register_instance(_managed_spec(root))

        def fail_firewall(value):
            calls.append("firewall")
            raise RuntimeError("firewall teardown failed")

        try:
            instance_runtime.resolve_adapter = lambda value: Adapter()
            privileged_firewall.remove = fail_firewall
            sys.modules["privileged_firewall"].remove = fail_firewall

            try:
                instance_runtime.lifecycle(
                    {"agent_id": "agent-one"},
                    "instance-one",
                    "stop",
                )
            except RuntimeError as exc:
                assert str(exc) == "firewall teardown failed"
            else:
                raise AssertionError("firewall teardown failure must propagate")

            assert calls == ["stop", "firewall"]
            stored = instance_runtime.get_instance("instance-one")
            assert stored["desired_state"] == "stopped"
            assert stored["observed_state"] == "stopped"
        finally:
            instance_runtime.resolve_adapter = old_resolve
            privileged_firewall.remove = old_firewall_remove
            sys.modules["privileged_firewall"].remove = old_firewall_remove
            instance_runtime.STATE_DIR = old_state
            instance_runtime.INSTANCE_DIR = old_instances
