#!/usr/bin/env python3
"""Regression tests for Controller-authoritative Hybrid RuntimeSpec port backfill."""

from __future__ import annotations

import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "dashboard" / "workers"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from hybrid_local_reconciliation import reconcile_local_hybrid_runtime
from hybrid_runtime_port_backfill import (
    HybridRuntimePortBackfillError,
    reconcile_hybrid_runtime_ports,
)
from hybrid_agent_worker import heartbeat_cycle


PALWORLD_NETWORK = {
    "allocation": "block",
    "block_size": 10,
    "ports": [
        {"name": "game", "protocol": "udp", "offset": 0, "exposure": "public"},
        {"name": "rcon", "protocol": "tcp", "offset": 1, "exposure": "none"},
        {"name": "rest_api", "protocol": "tcp", "offset": 2, "exposure": "none"},
    ],
}


class HybridRuntimePortBackfillTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "dsm"
        self.specs = self.root / "runtime" / "hybrid-agent-state" / "instances"
        self.specs.mkdir(parents=True)
        self.path = self.specs / "palworld-legacy.json"
        self.original = {
            "schema_version": 1,
            "kind": "CapivaraAgentInstance",
            "instance_id": "palworld-legacy",
            "agent_id": "agent-hybrid",
            "game_id": "palworld",
            "environment_id": "palworld.stable",
            "profile": "palworld",
            "profile_version": 3,
            "desired_state": "stopped",
            "ports": {
                "game": {"port": 24010, "protocol": "udp"},
            },
            "profile_context": {
                "install_path": "/opt/dsm/game-data/palworld/serverfiles",
                "ports": {
                    "game": {"port": 24010, "protocol": "udp"},
                },
            },
        }
        self.path.write_text(json.dumps(self.original), encoding="utf-8")
        self.backend = object()

    def tearDown(self):
        self.temp.cleanup()

    def _repository(self):
        repository = Mock()
        repository.instance_context.return_value = {
            "id": "palworld-legacy",
            "agent_id": "agent-hybrid",
            "node_id": "hybrid-node",
            "game_id": "palworld",
            "runtime_id": "palworld.stable",
        }
        return repository

    def test_backfill_persists_controller_reservations_in_runtime_spec(self):
        repository = self._repository()
        occupied = Mock(return_value=set())
        reconcile_result = {
            "instance_id": "palworld-legacy",
            "base_port": 24010,
            "ports": {
                "game": 24010,
                "rcon": 24011,
                "rest_api": 24012,
            },
            "inserted": ["rcon", "rest_api"],
            "changed": True,
        }

        with (
            patch(
                "hybrid_runtime_port_backfill.InstanceWorkspaceRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_runtime_port_backfill.occupied_ports_provider_for_backend",
                return_value=occupied,
            ),
            patch(
                "hybrid_runtime_port_backfill.runtime_definition",
                return_value={"id": "palworld.stable", "network": PALWORLD_NETWORK},
            ),
            patch(
                "hybrid_runtime_port_backfill.reconcile_instance_ports",
                return_value=reconcile_result,
            ) as reconcile_ports,
            patch("hybrid_runtime_port_backfill.os.chown"),
        ):
            result = reconcile_hybrid_runtime_ports(
                self.backend,
                self.root,
                "agent-hybrid",
            )

        reconcile_ports.assert_called_once_with(
            repository,
            "palworld-legacy",
            PALWORLD_NETWORK,
            occupied_ports_provider=occupied,
            runtime_stopped_proof=False,
        )
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        expected = {
            "game": {"port": 24010, "protocol": "udp"},
            "rcon": {"port": 24011, "protocol": "tcp"},
            "rest_api": {"port": 24012, "protocol": "tcp"},
        }
        self.assertEqual(persisted["ports"], expected)
        self.assertEqual(persisted["profile_context"]["ports"], expected)
        self.assertEqual(persisted["desired_state"], "stopped")
        self.assertEqual(result["reservations_backfilled"], 1)
        self.assertEqual(result["specs_updated"], 1)

    def test_verified_stopped_runtime_proof_is_forwarded(self):
        stopped = dict(self.original)
        stopped["observed_state"] = "stopped"
        self.path.write_text(json.dumps(stopped), encoding="utf-8")
        repository = self._repository()
        occupied = Mock(return_value=set())

        with (
            patch(
                "hybrid_runtime_port_backfill.InstanceWorkspaceRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_runtime_port_backfill.occupied_ports_provider_for_backend",
                return_value=occupied,
            ),
            patch(
                "hybrid_runtime_port_backfill.runtime_definition",
                return_value={"id": "palworld.stable", "network": PALWORLD_NETWORK},
            ),
            patch(
                "hybrid_runtime_port_backfill.reconcile_instance_ports",
                return_value={
                    "instance_id": "palworld-legacy",
                    "base_port": 24010,
                    "ports": {"game": 24010, "rcon": 24011, "rest_api": 24012},
                    "inserted": [],
                    "changed": False,
                },
            ) as reconcile_ports,
        ):
            reconcile_hybrid_runtime_ports(
                self.backend,
                self.root,
                "agent-hybrid",
            )

        reconcile_ports.assert_called_once_with(
            repository,
            "palworld-legacy",
            PALWORLD_NETWORK,
            occupied_ports_provider=occupied,
            runtime_stopped_proof=True,
        )

    def test_bedrock_legacy_runtime_policy_is_refreshed_from_current_catalog(self):
        instance_id = "cli-000001-minecraft-001"
        path = self.specs / f"{instance_id}.json"
        stale = {
            "schema_version": 1,
            "kind": "CapivaraAgentInstance",
            "instance_id": instance_id,
            "agent_id": "agent-hybrid",
            "game_id": "minecraft",
            "environment_id": "minecraft.bedrock.vanilla",
            "desired_state": "stopped",
            "observed_state": "stopped",
            "ports": {
                "gameplay_udp": {"port": 24007, "protocol": "udp"},
                "signaling": {"port": 24006, "protocol": "tcp"},
            },
            "profile_context": {
                "ports": {
                    "gameplay_udp": {"port": 24007, "protocol": "udp"},
                    "signaling": {"port": 24006, "protocol": "tcp"},
                },
            },
            "catalog_runtime_policy": {
                "runtime_id": "minecraft.bedrock.vanilla",
                "engine": "native",
                "network_exposure": [
                    {"name": "game_ipv4", "protocol": "udp", "exposure": "public"},
                    {"name": "game_ipv6", "protocol": "udp", "exposure": "public"},
                ],
            },
            "catalog_network_properties": [
                {
                    "path": "server.properties",
                    "key": "server-port",
                    "value": "{{PORT_GAME_IPV4}}",
                    "syntax": "equals",
                },
                {
                    "path": "server.properties",
                    "key": "server-portv6",
                    "value": "{{PORT_GAME_IPV6}}",
                    "syntax": "equals",
                },
            ],
            "catalog_variables": {
                "INSTANCE_ID": instance_id,
                "PORT_GAME_IPV4": "24006",
                "PORT_GAME_IPV6": "24007",
            },
        }
        path.write_text(json.dumps(stale), encoding="utf-8")
        self.path.unlink()

        network = {
            "allocation": "block",
            "block_size": 2,
            "ports": [
                {"name": "signaling", "protocol": "tcp", "offset": 0, "exposure": "public"},
                {"name": "gameplay_udp", "protocol": "udp", "offset": 1, "exposure": "public"},
            ],
            "apply": [
                {
                    "kind": "property",
                    "file": "server.properties",
                    "key": "server-port",
                    "value": "{signaling}",
                },
                {
                    "kind": "property",
                    "file": "server.properties",
                    "key": "server-udp-ports",
                    "value": "{gameplay_udp}",
                },
                {
                    "kind": "property",
                    "file": "server.properties",
                    "key": "transport",
                    "value": "nethernet",
                },
            ],
        }
        repository = Mock()
        repository.instance_context.return_value = {
            "id": instance_id,
            "agent_id": "agent-hybrid",
            "game_id": "minecraft",
            "runtime_id": "minecraft.bedrock.vanilla",
        }

        with (
            patch(
                "hybrid_runtime_port_backfill.InstanceWorkspaceRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_runtime_port_backfill.occupied_ports_provider_for_backend",
                return_value=Mock(return_value=set()),
            ),
            patch(
                "hybrid_runtime_port_backfill.runtime_definition",
                return_value={"id": "minecraft.bedrock.vanilla", "network": network},
            ),
            patch(
                "hybrid_runtime_port_backfill.reconcile_instance_ports",
                return_value={
                    "instance_id": instance_id,
                    "base_port": 24006,
                    "ports": {"signaling": 24006, "gameplay_udp": 24007},
                    "inserted": [],
                    "changed": False,
                },
            ),
            patch("hybrid_runtime_port_backfill.os.chown"),
        ):
            result = reconcile_hybrid_runtime_ports(
                self.backend,
                self.root,
                "agent-hybrid",
            )

        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["catalog_runtime_policy"]["network_exposure"],
            [
                {"name": "signaling", "protocol": "tcp", "exposure": "public"},
                {"name": "gameplay_udp", "protocol": "udp", "exposure": "public"},
            ],
        )
        self.assertEqual(
            persisted["catalog_network_properties"],
            [
                {
                    "path": "server.properties",
                    "key": "server-port",
                    "value": "{{PORT_SIGNALING}}",
                    "syntax": "equals",
                },
                {
                    "path": "server.properties",
                    "key": "server-udp-ports",
                    "value": "{{PORT_GAMEPLAY_UDP}}",
                    "syntax": "equals",
                },
                {
                    "path": "server.properties",
                    "key": "transport",
                    "value": "nethernet",
                    "syntax": "equals",
                },
            ],
        )
        self.assertEqual(persisted["catalog_variables"]["PORT_SIGNALING"], "24006")
        self.assertEqual(persisted["catalog_variables"]["PORT_GAMEPLAY_UDP"], "24007")
        self.assertNotIn("PORT_GAME_IPV4", persisted["catalog_variables"])
        self.assertNotIn("PORT_GAME_IPV6", persisted["catalog_variables"])
        self.assertEqual(result["specs_updated"], 1)

    def test_controller_reconcile_failure_leaves_runtime_spec_unchanged(self):
        repository = self._repository()
        before = self.path.read_text(encoding="utf-8")

        with (
            patch(
                "hybrid_runtime_port_backfill.InstanceWorkspaceRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_runtime_port_backfill.occupied_ports_provider_for_backend",
                return_value=Mock(return_value=set()),
            ),
            patch(
                "hybrid_runtime_port_backfill.runtime_definition",
                return_value={"id": "palworld.stable", "network": PALWORLD_NETWORK},
            ),
            patch(
                "hybrid_runtime_port_backfill.reconcile_instance_ports",
                side_effect=RuntimeError("port collision"),
            ),
        ):
            with self.assertRaises(HybridRuntimePortBackfillError):
                reconcile_hybrid_runtime_ports(
                    self.backend,
                    self.root,
                    "agent-hybrid",
                )

        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_complete_reservations_are_idempotent(self):
        complete = dict(self.original)
        complete["ports"] = {
            "game": {"port": 24010, "protocol": "udp"},
            "rcon": {"port": 24011, "protocol": "tcp"},
            "rest_api": {"port": 24012, "protocol": "tcp"},
        }
        complete["profile_context"] = dict(complete["profile_context"])
        complete["profile_context"]["ports"] = dict(complete["ports"])
        self.path.write_text(json.dumps(complete), encoding="utf-8")
        repository = self._repository()

        with (
            patch(
                "hybrid_runtime_port_backfill.InstanceWorkspaceRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_runtime_port_backfill.occupied_ports_provider_for_backend",
                return_value=Mock(return_value=set()),
            ),
            patch(
                "hybrid_runtime_port_backfill.runtime_definition",
                return_value={"id": "palworld.stable", "network": PALWORLD_NETWORK},
            ),
            patch(
                "hybrid_runtime_port_backfill.reconcile_instance_ports",
                return_value={
                    "instance_id": "palworld-legacy",
                    "base_port": 24010,
                    "ports": {"game": 24010, "rcon": 24011, "rest_api": 24012},
                    "inserted": [],
                    "changed": False,
                },
            ),
            patch("hybrid_runtime_port_backfill._write_spec") as write_spec,
        ):
            result = reconcile_hybrid_runtime_ports(
                self.backend,
                self.root,
                "agent-hybrid",
            )

        write_spec.assert_not_called()
        self.assertEqual(result["reservations_backfilled"], 0)
        self.assertEqual(result["specs_updated"], 0)

    def test_backfill_gate_precedes_hybrid_runtime_reconciler(self):
        local_source = inspect.getsource(reconcile_local_hybrid_runtime)
        heartbeat_source = inspect.getsource(heartbeat_cycle)

        self.assertLess(
            local_source.index("runtime.upsert_inventory"),
            local_source.index("reconcile_hybrid_runtime_ports"),
        )
        self.assertLess(
            heartbeat_source.index("reconcile_local_hybrid_runtime"),
            heartbeat_source.index("process_hybrid_instance_reconcile_cycle"),
        )


if __name__ == "__main__":
    unittest.main()
