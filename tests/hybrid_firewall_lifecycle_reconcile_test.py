#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import instance_runtime
import privileged_firewall


def _legacy_dayz_spec() -> dict:
    return {
        "instance_id": "cli-000001-dayz-001",
        "agent_id": "agent-horizon-server",
        "game_id": "dayz",
        "runtime_id": "dayz.stable",
        "adapter": "systemd",
        "catalog_runtime_policy": {
            "runtime_id": "dayz.stable",
            "shutdown": {"mode": "signal", "value": "TERM"},
        },
        "ports": {
            "game": {"port": 24000, "protocol": "udp"},
            "game_aux": {"port": 24002, "protocol": "udp"},
            "steam_query": {"port": 24003, "protocol": "udp"},
        },
    }


def test_hybrid_legacy_runtime_recovers_exposure_from_current_catalog():
    old_mode = os.environ.get("CAPIVARA_AGENT_MODE")
    old_root = os.environ.get("CAPIVARA_DSM_ROOT")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runtime_dir = root / "catalog" / "v2" / "games" / "dayz" / "runtimes"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "stable.json").write_text(
            json.dumps(
                {
                    "id": "dayz.stable",
                    "network": {
                        "ports": [
                            {"name": "game", "protocol": "udp", "offset": 0, "exposure": "public"},
                            {"name": "game_aux", "protocol": "udp", "offset": 2, "exposure": "public"},
                            {"name": "steam_query", "protocol": "udp", "offset": 3, "exposure": "public"},
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        try:
            os.environ["CAPIVARA_AGENT_MODE"] = "hybrid"
            os.environ["CAPIVARA_DSM_ROOT"] = str(root)
            assert privileged_firewall.public_rules(_legacy_dayz_spec()) == [
                {"name": "game", "protocol": "udp", "port": 24000},
                {"name": "game_aux", "protocol": "udp", "port": 24002},
                {"name": "steam_query", "protocol": "udp", "port": 24003},
            ]
        finally:
            if old_mode is None:
                os.environ.pop("CAPIVARA_AGENT_MODE", None)
            else:
                os.environ["CAPIVARA_AGENT_MODE"] = old_mode
            if old_root is None:
                os.environ.pop("CAPIVARA_DSM_ROOT", None)
            else:
                os.environ["CAPIVARA_DSM_ROOT"] = old_root


def test_lifecycle_reconciles_firewall_before_start():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_state = instance_runtime.STATE_DIR
        old_instances = instance_runtime.INSTANCE_DIR
        old_resolve = instance_runtime.resolve_adapter
        old_reconcile = privileged_firewall.reconcile
        calls: list[str] = []

        class Adapter:
            name = "systemd"

            def start(self, record):
                calls.append("start")
                return {
                    "changed": True,
                    "state": {"available": True, "active_state": "active", "running": True},
                }

        try:
            instance_runtime.STATE_DIR = root
            instance_runtime.INSTANCE_DIR = root / "instances"
            instance_runtime.resolve_adapter = lambda record: Adapter()
            privileged_firewall.reconcile = lambda record: (
                calls.append("firewall")
                or {"backend": "ufw", "changed": True, "rules": []}
            )
            instance_runtime.register_instance(_legacy_dayz_spec())

            result = instance_runtime.lifecycle(
                {"agent_id": "agent-horizon-server"},
                "cli-000001-dayz-001",
                "start",
            )

            assert calls == ["firewall", "start"]
            assert result["observed_state"] == "running"
            assert result["firewall"]["backend"] == "ufw"
        finally:
            instance_runtime.resolve_adapter = old_resolve
            privileged_firewall.reconcile = old_reconcile
            instance_runtime.STATE_DIR = old_state
            instance_runtime.INSTANCE_DIR = old_instances


def test_lifecycle_is_fail_closed_when_firewall_reconcile_fails():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_state = instance_runtime.STATE_DIR
        old_instances = instance_runtime.INSTANCE_DIR
        old_resolve = instance_runtime.resolve_adapter
        old_reconcile = privileged_firewall.reconcile
        calls: list[str] = []

        class Adapter:
            name = "systemd"

            def start(self, record):
                calls.append("start")
                raise AssertionError("runtime must not start after firewall failure")

        def fail_firewall(record):
            calls.append("firewall")
            raise RuntimeError("managed firewall failed")

        try:
            instance_runtime.STATE_DIR = root
            instance_runtime.INSTANCE_DIR = root / "instances"
            instance_runtime.resolve_adapter = lambda record: Adapter()
            privileged_firewall.reconcile = fail_firewall
            instance_runtime.register_instance(_legacy_dayz_spec())

            try:
                instance_runtime.lifecycle(
                    {"agent_id": "agent-horizon-server"},
                    "cli-000001-dayz-001",
                    "start",
                )
            except RuntimeError as exc:
                assert "managed firewall failed" in str(exc)
            else:
                raise AssertionError("firewall failure must fail lifecycle")

            assert calls == ["firewall"]
        finally:
            instance_runtime.resolve_adapter = old_resolve
            privileged_firewall.reconcile = old_reconcile
            instance_runtime.STATE_DIR = old_state
            instance_runtime.INSTANCE_DIR = old_instances


def test_stop_does_not_remove_or_reconcile_firewall():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_state = instance_runtime.STATE_DIR
        old_instances = instance_runtime.INSTANCE_DIR
        old_resolve = instance_runtime.resolve_adapter
        old_reconcile = privileged_firewall.reconcile
        calls: list[str] = []

        class Adapter:
            name = "systemd"

            def stop(self, record):
                calls.append("stop")
                return {
                    "changed": True,
                    "state": {"available": True, "active_state": "inactive", "running": False},
                }

        try:
            instance_runtime.STATE_DIR = root
            instance_runtime.INSTANCE_DIR = root / "instances"
            instance_runtime.resolve_adapter = lambda record: Adapter()
            privileged_firewall.reconcile = lambda record: calls.append("firewall")
            instance_runtime.register_instance(_legacy_dayz_spec())

            result = instance_runtime.lifecycle(
                {"agent_id": "agent-horizon-server"},
                "cli-000001-dayz-001",
                "stop",
            )

            assert calls == ["stop"]
            assert result["observed_state"] == "stopped"
            assert "firewall" not in result
        finally:
            instance_runtime.resolve_adapter = old_resolve
            privileged_firewall.reconcile = old_reconcile
            instance_runtime.STATE_DIR = old_state
            instance_runtime.INSTANCE_DIR = old_instances
