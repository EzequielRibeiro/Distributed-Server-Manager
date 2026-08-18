
#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"

sys.path.insert(
    0,
    str(DATABASE),
)


from agent_port_repository import (
    AgentPortRepository,
)
from backend import DatabaseConfig
from backend_factory import create_backend
from registry_repository import (
    RegistryRepository,
)


class AgentPortRepositoryTest(
    unittest.TestCase
):
    def setUp(self):
        self.temp = (
            tempfile.TemporaryDirectory()
        )

        backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(
                    Path(
                        self.temp.name
                    )
                    / "capivara.db"
                ),
            )
        )

        self.repository = (
            AgentPortRepository(
                backend
            )
        )

        self.repository.initialize()

        RegistryRepository(
            backend
        ).create_aurora(
            password_hash="hash",
            manifest_path="manifest",
            metadata_json="{}",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_default_ranges(self):
        summary = (
            self.repository.summary(
                "agent-demo"
            )
        )

        ranges = {
            (
                item["protocol"],
                int(
                    item["start_port"]
                ),
                int(
                    item["end_port"]
                ),
            )
            for item
            in summary["ranges"]
        }

        self.assertEqual(
            ranges,
            {
                (
                    "tcp",
                    24000,
                    24999,
                ),
                (
                    "udp",
                    24000,
                    24999,
                ),
            },
        )

    def test_change_range(self):
        self.repository.set_ranges(
            "agent-demo",
            protocols=(
                "tcp",
                "udp",
            ),
            start_port=30000,
            end_port=30999,
        )

        summary = (
            self.repository.summary(
                "agent-demo"
            )
        )

        self.assertTrue(
            all(
                int(
                    item["start_port"]
                )
                == 30000
                for item
                in summary["ranges"]
            )
        )


if __name__ == "__main__":
    unittest.main()
