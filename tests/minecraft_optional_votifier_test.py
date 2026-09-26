#!/usr/bin/env python3
"""Explicit Votifier opt-in, numeric ownership and safe stopped-Hybrid release."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for d in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

from core.network.optional_ports import enabled_network_profile
from core.network.port_profile import PortProfile
from instance_optional_port_service import (
    OptionalPortError, _catalog_role, _choose_tcp, _stopped, set_votifier,
)


class Result:
    def __init__(self, row=None, rows=None):
        self.row, self.rows = row, list(rows or [])

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class Session:
    def __init__(self, fixture):
        self.f = fixture

    def execute(self, sql, params=()):
        sql = " ".join(str(sql).split())
        f = self.f
        if sql.startswith("SELECT id,node_id,agent_id,status,metadata_json FROM instances"):
            return Result(row={"id": "mc-1", "node_id": "node-1", "agent_id": "agent-1",
                               "status": f.status, "metadata_json": json.dumps(f.meta)})
        if sql.startswith("SELECT id FROM nodes"):
            return Result(row={"id": "node-1"})
        if sql.startswith("SELECT port FROM instance_ports WHERE instance_id=") and "name='votifier'" in sql:
            return Result(row={"port": f.reserved["votifier"]} if "votifier" in f.reserved else None)
        if sql.startswith("SELECT port FROM instance_ports WHERE instance_id=") and "name='game'" in sql:
            return Result(row={"port": f.reserved["game"]})
        if sql.startswith("SELECT protocol,start_port,end_port FROM agent_port_ranges"):
            return Result(rows=[{"protocol": "tcp", "start_port": 24000, "end_port": 24050}])
        if sql.startswith("SELECT protocol,port FROM instance_ports WHERE node_id="):
            return Result(rows=[
                {"protocol": "tcp", "port": port} for port in f.reserved.values()
            ] + [{"protocol": "udp", "port": 24003}])
        if sql.startswith("INSERT INTO instance_ports"):
            assert params[2] == "votifier" and params[3] == "tcp"
            f.reserved["votifier"] = params[4]
            return Result()
        if sql.startswith("DELETE FROM instance_ports"):
            f.reserved.pop("votifier", None)
            return Result()
        if sql.startswith("UPDATE instances SET metadata_json="):
            f.meta = json.loads(params[0])
            return Result()
        raise AssertionError(f"Unexpected SQL: {sql}")


class Repo:
    def __init__(self, f):
        self.f = f
        self.backend = SimpleNamespace(name="sqlite")
        self.dialect = SimpleNamespace(placeholder="?", parameters=lambda n: ",".join("?" for _ in range(n)))

    def instance_context(self, instance_id):
        assert instance_id == "mc-1"
        return {
            "agent_id": "agent-1", "node_id": "node-1",
            "game_id": "minecraft", "runtime_id": "minecraft.java.paper",
            "instance_metadata": self.f.meta,
        }

    def session(self, **kwargs):
        from contextlib import nullcontext
        assert kwargs.get("transaction") is True
        return nullcontext(Session(self.f))


class Fixture:
    def __init__(self, root):
        self.root = root
        catalog = root / "catalog/v2/games/minecraft/runtimes"
        catalog.mkdir(parents=True)
        (catalog / "java-paper.json").write_text(
            (ROOT / "catalog/v2/games/minecraft/runtimes/java-paper.json").read_text(),
            encoding="utf-8",
        )
        self.status = "stopped"
        self.meta = {"network": {"ports": {"game": 24000, "rcon": 24001, "query": 24002}}}
        self.reserved = {"game": 24000, "rcon": 24001, "query": 24002}
        self.spec_path = root / "runtime/hybrid-agent-state/instances/mc-1.json"
        self.spec_path.parent.mkdir(parents=True)
        (self.spec_path.parent.parent / "agent.json").write_text(
            json.dumps({"agent_id": "agent-1"}), encoding="utf-8",
        )
        self.sync()

    def sync(self):
        ports = {
            name: {"protocol": "udp" if name == "query" else "tcp", "port": value}
            for name, value in self.reserved.items()
        }
        if self.meta.get("network_optional_pending_drop"):
            ports.pop("votifier", None)
        self.spec_path.write_text(json.dumps({
            "agent_id": "agent-1", "instance_id": "mc-1",
            "ports": ports,
        }), encoding="utf-8")


class OptionalVotifierTest(unittest.TestCase):
    def test_all_eligible_java_runtimes_allocate_only_on_request(self):
        directory = ROOT / "catalog/v2/games/minecraft/runtimes"
        for path in sorted(directory.glob("java-*.json")):
            runtime = json.loads(path.read_text())
            default = enabled_network_profile(runtime)
            self.assertEqual({item["name"] for item in default["ports"]}, {"game", "rcon", "query"})
            self.assertIsNotNone(PortProfile.from_mapping(default))
            if runtime["id"] == "minecraft.java.vanilla":
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    enabled_network_profile(runtime, optional_roles=frozenset({"votifier"}))
            else:
                opted = enabled_network_profile(runtime, optional_roles=frozenset({"votifier"}))
                self.assertEqual({item["name"] for item in opted["ports"]},
                                 {"game", "rcon", "query", "votifier"})
                self.assertIn({"kind": "reserve", "port": "votifier"}, opted["apply"])

    def test_schema_and_vanilla_refuse_unsupported_activation(self):
        with self.assertRaisesRegex(OptionalPortError, "não oferece"):
            _catalog_role(ROOT, "minecraft", "minecraft.java.vanilla", enable=True)
        self.assertEqual(
            _catalog_role(ROOT, "minecraft", "minecraft.java.paper", enable=True)["protocol"],
            "tcp",
        )

    def test_stopped_check_requires_loaded_systemd_unit(self):
        for output, permitted in (
            ("LoadState=loaded\nActiveState=inactive\n", True),
            ("LoadState=not-found\nActiveState=inactive\n", False),
            ("LoadState=loaded\nActiveState=active\n", False),
            ("ActiveState=inactive\n", False),
        ):
            with self.subTest(output=output), patch(
                "instance_optional_port_service.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=output),
            ):
                if permitted:
                    _stopped("mc-1")
                else:
                    with self.assertRaises(OptionalPortError):
                        _stopped("mc-1")

    def test_allocator_uses_free_numeric_port_when_preferred_is_owned(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            provider = lambda _agent, _node, proto, _low, _high: {24004} if proto == "udp" else set()
            self.assertEqual(_choose_tcp(
                Session(f), "?", provider, "agent-1", "node-1", 24003,
            ), 24005)

    def test_hybrid_enable_retry_and_release_are_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            repo = Repo(f)
            provider = lambda _a, _n, proto, _start, _end: {24004} if proto == "udp" else set()
            with (
                patch("instance_optional_port_service.InstanceWorkspaceRepository", return_value=repo),
                patch("instance_optional_port_service._stopped"),
                patch("instance_optional_port_service._sync", side_effect=lambda *_: f.sync()),
                patch("instance_optional_port_service.occupied_ports_provider_for_backend",
                      return_value=provider),
            ):
                one = set_votifier(repo.backend, f.root, "mc-1", enabled=True)
                self.assertEqual(one, {"status": "enabled", "port": 24005})
                self.assertEqual(f.reserved["votifier"], 24005)
                self.assertEqual(
                    set_votifier(repo.backend, f.root, "mc-1", enabled=True)["port"],
                    24005,
                )
                f.status = "online"
                with self.assertRaisesRegex(OptionalPortError, "parada"):
                    set_votifier(repo.backend, f.root, "mc-1", enabled=False)
                f.status = "stopped"
                result = set_votifier(repo.backend, f.root, "mc-1", enabled=False)
                self.assertEqual(result["status"], "disabled")
                self.assertNotIn("votifier", f.reserved)
                self.assertNotIn("votifier", json.loads(f.spec_path.read_text())["ports"])

    def test_sync_failure_keeps_reserved_port_and_retry_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Fixture(Path(tmp))
            repo = Repo(f)
            with (
                patch("instance_optional_port_service.InstanceWorkspaceRepository", return_value=repo),
                patch("instance_optional_port_service._stopped"),
                patch("instance_optional_port_service._sync", side_effect=RuntimeError("offline")),
                patch("instance_optional_port_service.occupied_ports_provider_for_backend",
                      return_value=lambda *_: set()),
            ):
                result = set_votifier(repo.backend, f.root, "mc-1", enabled=True)
                self.assertEqual(result["status"], "pending_sync")
                self.assertIn("votifier", f.reserved)
            # Never report a remote instance as changed without an Agent binding.
            f.spec_path.unlink()
            with patch("instance_optional_port_service.InstanceWorkspaceRepository", return_value=repo):
                with self.assertRaisesRegex(OptionalPortError, "híbrido"):
                    set_votifier(repo.backend, f.root, "mc-1", enabled=True)


if __name__ == "__main__":
    unittest.main()
