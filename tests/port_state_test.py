#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from core.network.port_state import build_port_states


class PortStateTest(unittest.TestCase):
    def test_reserved_and_listening_states(self):
        result = build_port_states(
            [
                {
                    "name": "game",
                    "protocol": "udp",
                    "port": 24000,
                    "bind_address": "0.0.0.0",
                },
                {
                    "name": "query",
                    "protocol": "udp",
                    "port": 24002,
                    "bind_address": "0.0.0.0",
                },
            ],
            listening={"udp": {24000}},
        )

        states = {item.name: item.state for item in result}

        self.assertEqual(states["game"], "listening")
        self.assertEqual(states["query"], "reserved")


if __name__ == "__main__":
    unittest.main()
