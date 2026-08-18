
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
