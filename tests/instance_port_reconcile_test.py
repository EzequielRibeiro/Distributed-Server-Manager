#!/usr/bin/env python3
from __future__ import annotations

import unittest

from core.network.port_allocator import PortRange
from core.network.port_profile import PortProfile, PortRequirement
from database.instance_port_reconcile import (
    InstancePortReconcileError,
    plan_instance_port_reconcile,
)


PROFILE = PortProfile.from_mapping(
    {
        "allocation": "block",
        "block_size": 10,
        "ports": [
            {"name": "game", "protocol": "udp", "offset": 0},
            {"name": "rcon", "protocol": "tcp", "offset": 1},
            {"name": "rest_api", "protocol": "tcp", "offset": 2},
        ],
    }
)
RANGES = (
    PortRange("udp", 24000, 24999),
    PortRange("tcp", 24000, 24999),
)


class InstancePortReconcilePlanTest(unittest.TestCase):
    def test_backfills_missing_palworld_roles_from_existing_game_anchor(self):
        plan = plan_instance_port_reconcile(
            PROFILE,
            [
                {
                    "name": "game",
                    "protocol": "udp",
                    "port": 24010,
                    "bind_address": "0.0.0.0",
                }
            ],
            RANGES,
        )
        self.assertEqual(plan.base_port, 24010)
        self.assertEqual(
            plan.ports,
            {"game": 24010, "rcon": 24011, "rest_api": 24012},
        )
        self.assertEqual(plan.missing, ("rcon", "rest_api"))

    def test_is_idempotent_when_profile_is_fully_persisted(self):
        plan = plan_instance_port_reconcile(
            PROFILE,
            [
                {"name": "game", "protocol": "udp", "port": 24010},
                {"name": "rcon", "protocol": "tcp", "port": 24011},
                {"name": "rest_api", "protocol": "tcp", "port": 24012},
            ],
            RANGES,
        )
        self.assertEqual(plan.missing, ())
        self.assertEqual(plan.ports["game"], 24010)

    def test_rejects_collision_with_other_instance(self):
        with self.assertRaisesRegex(InstancePortReconcileError, "collides"):
            plan_instance_port_reconcile(
                PROFILE,
                [{"name": "game", "protocol": "udp", "port": 24010}],
                RANGES,
                conflicts={"tcp": {24011}, "udp": set()},
            )

    def test_rejects_cross_protocol_collision_with_other_instance(self):
        with self.assertRaisesRegex(InstancePortReconcileError, "collides"):
            plan_instance_port_reconcile(
                PROFILE,
                [{"name": "game", "protocol": "udp", "port": 24010}],
                RANGES,
                conflicts={"tcp": set(), "udp": {24011}},
            )

    def test_rejects_persisted_anchor_owned_by_other_instance_on_other_protocol(self):
        with self.assertRaisesRegex(InstancePortReconcileError, "collides"):
            plan_instance_port_reconcile(
                PROFILE,
                [
                    {"name": "game", "protocol": "udp", "port": 24010},
                    {"name": "rcon", "protocol": "tcp", "port": 24011},
                    {"name": "rest_api", "protocol": "tcp", "port": 24012},
                ],
                RANGES,
                conflicts={"tcp": {24010}, "udp": set()},
            )

    def test_rejects_cross_protocol_unmanaged_socket_on_missing_port(self):
        with self.assertRaisesRegex(InstancePortReconcileError, "unmanaged socket"):
            plan_instance_port_reconcile(
                PROFILE,
                [{"name": "game", "protocol": "udp", "port": 24010}],
                RANGES,
                occupied={"tcp": set(), "udp": {24011}},
            )

    def test_rejects_unmanaged_socket_on_missing_port(self):
        with self.assertRaisesRegex(InstancePortReconcileError, "unmanaged socket"):
            plan_instance_port_reconcile(
                PROFILE,
                [{"name": "game", "protocol": "udp", "port": 24010}],
                RANGES,
                occupied={"tcp": {24012}, "udp": set()},
            )

    def test_rejects_existing_role_protocol_mismatch(self):
        with self.assertRaisesRegex(InstancePortReconcileError, "protocol mismatch"):
            plan_instance_port_reconcile(
                PROFILE,
                [
                    {"name": "game", "protocol": "udp", "port": 24010},
                    {"name": "rcon", "protocol": "udp", "port": 24011},
                ],
                RANGES,
            )

    def test_rejects_existing_roles_from_different_blocks(self):
        with self.assertRaisesRegex(InstancePortReconcileError, "logical port block"):
            plan_instance_port_reconcile(
                PROFILE,
                [
                    {"name": "game", "protocol": "udp", "port": 24010},
                    {"name": "rcon", "protocol": "tcp", "port": 24021},
                ],
                RANGES,
            )

    def test_rejects_derived_port_outside_active_range(self):
        with self.assertRaisesRegex(InstancePortReconcileError, "outside active Agent ranges"):
            plan_instance_port_reconcile(
                PROFILE,
                [{"name": "game", "protocol": "udp", "port": 24010}],
                (
                    PortRange("udp", 24000, 24999),
                    PortRange("tcp", 24100, 24999),
                ),
            )

    def test_rejects_profile_without_existing_anchor(self):
        with self.assertRaisesRegex(InstancePortReconcileError, "no persisted"):
            plan_instance_port_reconcile(PROFILE, [], RANGES)


    def test_new_vanilla_does_not_backfill_votifier_but_retains_legacy(self):
        vanilla = PortProfile.from_reservations({
            "allocation": "block", "block_size": 4,
            "ports": [
                {"name": "game", "protocol": "tcp", "offset": 0},
                {"name": "rcon", "protocol": "tcp", "offset": 1},
                {"name": "query", "protocol": "udp", "offset": 2},
            ],
        })
        legacy = {"votifier": PortRequirement("votifier", "tcp", 3)}
        base_rows = [
            {"name": "game", "protocol": "tcp", "port": 24012},
            {"name": "rcon", "protocol": "tcp", "port": 24013},
            {"name": "query", "protocol": "udp", "port": 24014},
        ]
        new = plan_instance_port_reconcile(vanilla, base_rows, RANGES, legacy_reservations=legacy)
        self.assertNotIn("votifier", new.ports)
        self.assertEqual(new.missing, ())
        old = plan_instance_port_reconcile(vanilla, [
            *base_rows, {"name": "votifier", "protocol": "tcp", "port": 24015},
        ], RANGES, legacy_reservations=legacy)
        self.assertEqual(old.ports["votifier"], 24015)
        self.assertEqual(old.missing, ())
        with self.assertRaisesRegex(InstancePortReconcileError, "logical port block"):
            plan_instance_port_reconcile(vanilla, [
                *base_rows, {"name": "votifier", "protocol": "tcp", "port": 24019},
            ], RANGES, legacy_reservations=legacy)
        with self.assertRaisesRegex(InstancePortReconcileError, "outside the current runtime profile"):
            plan_instance_port_reconcile(vanilla, [
                *base_rows, {"name": "untrusted", "protocol": "tcp", "port": 24015},
            ], RANGES, legacy_reservations=legacy)


if __name__ == "__main__":
    unittest.main()
