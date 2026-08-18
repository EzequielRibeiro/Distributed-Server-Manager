
#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(ROOT / "dashboard"),
)


from instance_network import (
    apply_instance_network,
    occupied_ports_for_agent,
)
from core.network.port_inspector import (
    PortInspectionError,
)


class InstanceNetworkTest(
    unittest.TestCase
):
    def test_port_inspection_requires_local_node_identity(self):
        with patch.dict(
            os.environ,
            {},
            clear=False,
        ):
            os.environ.pop(
                "DSM_LOCAL_NODE_ID",
                None,
            )

            with self.assertRaises(
                PortInspectionError
            ):
                occupied_ports_for_agent(
                    "agent-demo",
                    "node-demo",
                    "udp",
                    24000,
                    24999,
                )

    def test_remote_node_fails_closed(self):
        with patch.dict(
            os.environ,
            {
                "DSM_LOCAL_NODE_ID": "node-local",
            },
        ):
            with self.assertRaises(
                PortInspectionError
            ):
                occupied_ports_for_agent(
                    "agent-remote",
                    "node-remote",
                    "udp",
                    24000,
                    24999,
                )

    def test_arguments_are_rendered(self):
        with tempfile.TemporaryDirectory() as temp:
            instance = Path(temp)

            result = apply_instance_network(
                instance,
                {
                    "network": {
                        "allocation": "block",
                        "block_size": 10,
                        "ports": [
                            {
                                "name": "game",
                                "protocol": "udp",
                                "offset": 0,
                            }
                        ],
                        "apply": [
                            {
                                "kind": "argument",
                                "template": "-port={game}",
                            }
                        ],
                    }
                },
                {
                    "game": 24000,
                },
            )

            self.assertEqual(
                result["arguments"],
                [
                    "-port=24000",
                ],
            )

            self.assertEqual(
                result["environment"][
                    "PORT_GAME"
                ],
                24000,
            )

    def test_properties_are_written(self):
        with tempfile.TemporaryDirectory() as temp:
            instance = Path(temp)
            serverfiles = (
                instance
                / "serverfiles"
            )

            serverfiles.mkdir()

            properties = (
                serverfiles
                / "server.properties"
            )

            properties.write_text(
                "server-port=19132\n",
                encoding="utf-8",
            )

            apply_instance_network(
                instance,
                {
                    "network": {
                        "allocation": "block",
                        "block_size": 2,
                        "ports": [
                            {
                                "name": "game_ipv4",
                                "protocol": "udp",
                                "offset": 0,
                            }
                        ],
                        "apply": [
                            {
                                "kind": "property",
                                "file": "server.properties",
                                "key": "server-port",
                                "value": "{game_ipv4}",
                            }
                        ],
                    }
                },
                {
                    "game_ipv4": 24000,
                },
            )

            self.assertIn(
                "server-port=24000",
                properties.read_text(
                    encoding="utf-8"
                ),
            )


if __name__ == "__main__":
    unittest.main()
