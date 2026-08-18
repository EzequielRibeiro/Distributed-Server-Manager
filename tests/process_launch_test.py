#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from core.runtime.process_launch import build_process_launch_spec


class ProcessLaunchTest(unittest.TestCase):
    def test_ports_and_network_are_combined(self):
        definition = {
            "process": {
                "executable": "./server",
                "working_dir": "serverfiles",
                "args": ["-config=test.cfg"],
            }
        }

        result = build_process_launch_spec(
            definition,
            ports={"game": 24000},
            network_arguments=["-port=24000"],
            network_environment={"PORT_QUERY": 24001},
        )

        self.assertEqual(
            result.argv,
            ("-config=test.cfg", "-port=24000"),
        )

        self.assertEqual(
            result.environment["PORT_GAME"],
            "24000",
        )

        self.assertEqual(
            result.environment["PORT_QUERY"],
            "24001",
        )


if __name__ == "__main__":
    unittest.main()
