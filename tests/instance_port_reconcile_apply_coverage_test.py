#!/usr/bin/env python3
"""Regression coverage for reservation reconciliation independent of network.apply."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from core.network.port_profile import PortProfile
from instance_port_reconcile import reconcile_instance_ports


PALWORLD_NETWORK = {
    "allocation": "block",
    "block_size": 10,
    "ports": [
        {"name": "game", "protocol": "udp", "offset": 0, "exposure": "public"},
        {"name": "rcon", "protocol": "tcp", "offset": 1, "exposure": "none"},
        {"name": "rest_api", "protocol": "tcp", "offset": 2, "exposure": "none"},
    ],
    # Catalog applies only the public game port. Palworld's Runtime Profile
    # consumes rcon/rest_api when it renders PalWorldSettings.ini.
    "apply": [
        {"kind": "argument", "template": "-port={game}"},
    ],
}


class _Result:
    def __init__(self, *, one=None, many=None):
        self._one = one
        self._many = list(many or [])

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._many)


class _Session:
    def __init__(self, *, status="offline", existing=None, others=None):
        self.updated_metadata = None
        self.status = status
        self.existing = list(existing or [
            {"name": "game", "protocol": "udp", "port": 24010, "bind_address": "0.0.0.0"},
            {"name": "rcon", "protocol": "tcp", "port": 24011, "bind_address": "0.0.0.0"},
            {"name": "rest_api", "protocol": "tcp", "port": 24012, "bind_address": "0.0.0.0"},
        ])
        self.others = list(others or [])
        self.deleted = False
        self.inserted = []

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split())
        if normalized.startswith("SELECT id,node_id,agent_id,status,metadata_json FROM instances"):
            return _Result(one={
                "id": "cli-000001-palworld-001",
                "node_id": "horizon-server",
                "agent_id": "agent-horizon-server",
                "status": self.status,
                "metadata_json": "{}",
            })
        if normalized.startswith("SELECT protocol,start_port,end_port FROM agent_port_ranges"):
            return _Result(many=[
                {"protocol": "tcp", "start_port": 24000, "end_port": 24999},
                {"protocol": "udp", "start_port": 24000, "end_port": 24999},
            ])
        if normalized.startswith("SELECT name,protocol,port,bind_address FROM instance_ports"):
            return _Result(many=self.existing)
        if normalized.startswith("SELECT protocol,port FROM instance_ports"):
            return _Result(many=self.others)
        if normalized.startswith("SELECT instance_id FROM instance_ports WHERE node_id="):
            node_id, port, instance_id = params
            for row in self.others:
                if int(row.get("port")) == int(port):
                    return _Result(one={"instance_id": "other-instance"})
            return _Result(one=None)
        if normalized.startswith("DELETE FROM instance_ports"):
            self.deleted = True
            return _Result()
        if normalized.startswith("INSERT INTO instance_ports"):
            self.inserted.append(tuple(params))
            return _Result()
        if normalized.startswith("UPDATE instances SET metadata_json="):
            self.updated_metadata = params[0]
            return _Result()
        raise AssertionError(f"unexpected SQL: {normalized}")


class _SessionContext:
    def __init__(self, session):
        self.session = session

    def __enter__(self):
        return self.session

    def __exit__(self, exc_type, exc, tb):
        return False


class _Dialect:
    placeholder = "?"

    @staticmethod
    def parameters(count):
        return ",".join("?" for _ in range(count))


class _Backend:
    name = "sqlite"


class _Repository:
    def __init__(self, session=None):
        self.backend = _Backend()
        self.dialect = _Dialect()
        self.test_session = session or _Session()
        self.initialized = False

    def initialize(self):
        self.initialized = True

    def session(self, *, transaction=False):
        if not transaction:
            raise AssertionError("reconciliation must be transactional")
        return _SessionContext(self.test_session)


class InstancePortReconcileApplyCoverageTest(unittest.TestCase):
    def test_strict_catalog_parser_still_rejects_unapplied_reserved_roles(self):
        with self.assertRaisesRegex(
            ValueError,
            "network ports are reserved but not applied: rcon, rest_api",
        ):
            PortProfile.from_mapping(PALWORLD_NETWORK)

    def test_reservation_parser_accepts_runtime_profile_managed_roles(self):
        profile = PortProfile.from_reservations(PALWORLD_NETWORK)
        self.assertIsNotNone(profile)
        self.assertEqual(
            [(item.name, item.protocol, item.offset) for item in profile.ports],
            [
                ("game", "udp", 0),
                ("rcon", "tcp", 1),
                ("rest_api", "tcp", 2),
            ],
        )
        self.assertEqual(profile.applications, ())

    def test_reservation_parser_keeps_block_validation(self):
        invalid = dict(PALWORLD_NETWORK)
        invalid["block_size"] = 2
        with self.assertRaisesRegex(
            ValueError,
            "network port offset must fit inside block_size",
        ):
            PortProfile.from_reservations(invalid)

    def test_reconcile_accepts_complete_db_reservations_when_apply_is_partial(self):
        repository = _Repository()

        def unexpected_occupancy_probe(*_args, **_kwargs):
            raise AssertionError("complete reservations must not probe OS occupancy")

        result = reconcile_instance_ports(
            repository,
            "cli-000001-palworld-001",
            PALWORLD_NETWORK,
            occupied_ports_provider=unexpected_occupancy_probe,
        )

        self.assertTrue(repository.initialized)
        self.assertEqual(result["base_port"], 24010)
        self.assertEqual(
            result["ports"],
            {"game": 24010, "rcon": 24011, "rest_api": 24012},
        )
        self.assertEqual(result["inserted"], [])
        self.assertFalse(result["changed"])
        self.assertFalse(result["relocated"])
        self.assertIsNotNone(repository.test_session.updated_metadata)

    def test_expanded_minecraft_profile_relocates_offline_legacy_block_on_collision(self):
        network = {
            "allocation": "block",
            "block_size": 4,
            "ports": [
                {"name": "game", "protocol": "tcp", "offset": 0},
                {"name": "rcon", "protocol": "tcp", "offset": 1},
                {"name": "query", "protocol": "udp", "offset": 2},
                {"name": "votifier", "protocol": "tcp", "offset": 3},
            ],
        }
        session = _Session(
            existing=[
                {"name": "game", "protocol": "tcp", "port": 24000, "bind_address": "0.0.0.0"},
                {"name": "rcon", "protocol": "tcp", "port": 24001, "bind_address": "0.0.0.0"},
            ],
            others=[
                {"protocol": "udp", "port": 24000},
                {"protocol": "udp", "port": 24002},
                {"protocol": "udp", "port": 24003},
            ],
        )
        repository = _Repository(session)

        result = reconcile_instance_ports(
            repository,
            "cli-000001-minecraft-001",
            network,
            occupied_ports_provider=lambda *_args, **_kwargs: set(),
        )

        self.assertTrue(result["changed"])
        self.assertTrue(result["relocated"])
        self.assertEqual(result["previous_ports"], {"game": 24000, "rcon": 24001})
        self.assertEqual(
            result["ports"],
            {"game": 24004, "rcon": 24005, "query": 24006, "votifier": 24007},
        )
        self.assertTrue(session.deleted)
        self.assertEqual(len(session.inserted), 4)

    def test_bedrock_nethernnet_role_migration_relocates_stopped_legacy_block(self):
        network = {
            "allocation": "block",
            "block_size": 2,
            "ports": [
                {"name": "signaling", "protocol": "tcp", "offset": 0},
                {"name": "gameplay_udp", "protocol": "udp", "offset": 1},
            ],
        }
        session = _Session(
            status="stopped",
            existing=[
                {"name": "game_ipv4", "protocol": "udp", "port": 24006, "bind_address": "0.0.0.0"},
                {"name": "game_ipv6", "protocol": "udp", "port": 24007, "bind_address": "0.0.0.0"},
            ],
        )
        repository = _Repository(session)

        result = reconcile_instance_ports(
            repository,
            "cli-000001-minecraft-001",
            network,
            occupied_ports_provider=lambda *_args, **_kwargs: set(),
        )

        self.assertTrue(result["changed"])
        self.assertTrue(result["relocated"])
        self.assertEqual(
            result["previous_ports"],
            {"game_ipv4": 24006, "game_ipv6": 24007},
        )
        self.assertEqual(
            result["ports"],
            {"signaling": 24000, "gameplay_udp": 24001},
        )
        self.assertTrue(session.deleted)
        self.assertEqual(len(session.inserted), 2)

    def test_bedrock_nethernnet_role_migration_refuses_running_instance(self):
        network = {
            "allocation": "block",
            "block_size": 2,
            "ports": [
                {"name": "signaling", "protocol": "tcp", "offset": 0},
                {"name": "gameplay_udp", "protocol": "udp", "offset": 1},
            ],
        }
        repository = _Repository(_Session(
            status="running",
            existing=[
                {"name": "game_ipv4", "protocol": "udp", "port": 24006, "bind_address": "0.0.0.0"},
                {"name": "game_ipv6", "protocol": "udp", "port": 24007, "bind_address": "0.0.0.0"},
            ],
        ))

        with self.assertRaisesRegex(Exception, "cannot relocate network block while instance status is running"):
            reconcile_instance_ports(
                repository,
                "cli-000001-minecraft-001",
                network,
                occupied_ports_provider=lambda *_args, **_kwargs: set(),
            )

    def test_role_migration_accepts_explicit_runtime_stopped_proof(self):
        network = {
            "allocation": "block",
            "block_size": 2,
            "ports": [
                {"name": "signaling", "protocol": "tcp", "offset": 0},
                {"name": "gameplay_udp", "protocol": "udp", "offset": 1},
            ],
        }
        repository = _Repository(_Session(
            status="online",
            existing=[
                {"name": "game_ipv4", "protocol": "udp", "port": 24006, "bind_address": "0.0.0.0"},
                {"name": "game_ipv6", "protocol": "udp", "port": 24007, "bind_address": "0.0.0.0"},
            ],
        ))

        result = reconcile_instance_ports(
            repository,
            "cli-000001-minecraft-001",
            network,
            occupied_ports_provider=lambda *_args, **_kwargs: set(),
            runtime_stopped_proof=True,
        )

        self.assertTrue(result["relocated"])
        self.assertEqual(
            result["ports"],
            {"signaling": 24000, "gameplay_udp": 24001},
        )

    def test_expanded_profile_refuses_relocation_while_instance_is_running(self):
        network = {
            "allocation": "block",
            "block_size": 4,
            "ports": [
                {"name": "game", "protocol": "tcp", "offset": 0},
                {"name": "rcon", "protocol": "tcp", "offset": 1},
                {"name": "query", "protocol": "udp", "offset": 2},
                {"name": "votifier", "protocol": "tcp", "offset": 3},
            ],
        }
        repository = _Repository(_Session(
            status="running",
            existing=[
                {"name": "game", "protocol": "tcp", "port": 24000, "bind_address": "0.0.0.0"},
                {"name": "rcon", "protocol": "tcp", "port": 24001, "bind_address": "0.0.0.0"},
            ],
            others=[{"protocol": "udp", "port": 24002}],
        ))

        with self.assertRaisesRegex(Exception, "cannot relocate network block while instance status is running"):
            reconcile_instance_ports(
                repository,
                "cli-000001-minecraft-001",
                network,
                occupied_ports_provider=lambda *_args, **_kwargs: set(),
            )


if __name__ == "__main__":
    unittest.main()
