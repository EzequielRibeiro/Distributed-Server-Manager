
#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(ROOT),
)


from core.network.port_allocator import (
    PortAllocationError,
    PortRange,
    allocate_port_profile,
)
from core.network.port_profile import (
    PortProfile,
)


DAYZ = {
    "allocation": "block",
    "block_size": 10,
    "ports": [
        {
            "name": "game",
            "protocol": "udp",
            "offset": 0,
        },
        {
            "name": "game_aux",
            "protocol": "udp",
            "offset": 2,
        },
    ],
}


class PortAllocatorTest(
    unittest.TestCase
):
    def test_block_policy(self):
        profile = PortProfile.from_mapping(
            DAYZ
        )

        allocation = allocate_port_profile(
            profile,
            [
                PortRange(
                    "udp",
                    24000,
                    24999,
                )
            ],
            occupied={
                "udp": {
                    24000,
                    24002,
                }
            },
        )

        self.assertEqual(
            allocation.ports[
                "game"
            ],
            24010,
        )

        self.assertEqual(
            allocation.ports[
                "game_aux"
            ],
            24012,
        )

    def test_mixed_protocol_profile(self):
        profile = PortProfile.from_mapping(
            {
                "allocation": "block",
                "block_size": 10,
                "ports": [
                    {
                        "name": "game",
                        "protocol": "udp",
                        "offset": 0,
                    },
                    {
                        "name": "rcon",
                        "protocol": "tcp",
                        "offset": 1,
                    },
                ],
            }
        )

        allocation = allocate_port_profile(
            profile,
            [
                PortRange(
                    "udp",
                    24000,
                    24999,
                ),
                PortRange(
                    "tcp",
                    24000,
                    24999,
                ),
            ],
            reserved={
                "udp": set(),
                "tcp": {
                    24001,
                },
            },
        )

        self.assertEqual(
            allocation.ports,
            {
                "game": 24010,
                "rcon": 24011,
            },
        )

    def test_cross_protocol_reservation_blocks_numeric_port(self):
        profile = PortProfile.from_mapping(
            {
                "allocation": "block",
                "block_size": 2,
                "ports": [
                    {"name": "game", "protocol": "tcp", "offset": 0},
                    {"name": "rcon", "protocol": "tcp", "offset": 1},
                ],
            }
        )

        allocation = allocate_port_profile(
            profile,
            [
                PortRange("tcp", 24000, 24999),
                PortRange("udp", 24000, 24999),
            ],
            reserved={"udp": {24000}, "tcp": set()},
        )

        self.assertEqual(allocation.ports, {"game": 24002, "rcon": 24003})

    def test_cross_protocol_unmanaged_listener_blocks_numeric_port(self):
        profile = PortProfile.from_mapping(
            {
                "allocation": "block",
                "block_size": 2,
                "ports": [
                    {"name": "game", "protocol": "tcp", "offset": 0},
                    {"name": "rcon", "protocol": "tcp", "offset": 1},
                ],
            }
        )

        allocation = allocate_port_profile(
            profile,
            [
                PortRange("tcp", 24000, 24999),
                PortRange("udp", 24000, 24999),
            ],
            occupied={"udp": {24000}, "tcp": set()},
        )

        self.assertEqual(allocation.ports["game"], 24002)

    def test_same_instance_may_bind_same_number_on_tcp_and_udp(self):
        profile = PortProfile.from_mapping(
            {
                "allocation": "block",
                "block_size": 1,
                "ports": [
                    {"name": "game_udp", "protocol": "udp", "offset": 0},
                    {"name": "game_tcp", "protocol": "tcp", "offset": 0},
                ],
            }
        )

        allocation = allocate_port_profile(
            profile,
            [
                PortRange("tcp", 24000, 24999),
                PortRange("udp", 24000, 24999),
            ],
        )

        self.assertEqual(
            allocation.ports,
            {"game_udp": 24000, "game_tcp": 24000},
        )

    def test_sparse_offset_profile_keeps_block_stride(self):
        profile = PortProfile.from_mapping(
            {
                "allocation": "block",
                "block_size": 10,
                "sparse_offsets": True,
                "ports": [
                    {"name": "game", "protocol": "udp", "offset": 0},
                    {"name": "game_aux", "protocol": "udp", "offset": 2},
                    {"name": "steam_query", "protocol": "udp", "offset": 24714},
                ],
            }
        )

        allocation = allocate_port_profile(
            profile,
            [
                PortRange("udp", 24000, 24999),
                PortRange("udp", 48714, 49713),
            ],
            occupied={"udp": {24000}},
        )

        self.assertEqual(
            allocation.ports,
            {
                "game": 24010,
                "game_aux": 24012,
                "steam_query": 48724,
            },
        )

    def test_large_offset_requires_sparse_opt_in(self):
        with self.assertRaisesRegex(
            ValueError,
            "network port offset must fit inside block_size",
        ):
            PortProfile.from_mapping(
                {
                    "allocation": "block",
                    "block_size": 10,
                    "ports": [
                        {"name": "game", "protocol": "udp", "offset": 0},
                        {"name": "query", "protocol": "udp", "offset": 24714},
                    ],
                }
            )

    def test_exhausted_range(self):
        profile = PortProfile.from_mapping(
            DAYZ
        )

        with self.assertRaises(
            PortAllocationError
        ):
            allocate_port_profile(
                profile,
                [
                    PortRange(
                        "udp",
                        24000,
                        24009,
                    )
                ],
                occupied={
                    "udp": {
                        24000,
                    }
                },
            )


if __name__ == "__main__":
    unittest.main()
