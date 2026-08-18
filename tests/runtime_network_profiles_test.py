
#!/usr/bin/env python3

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(ROOT),
)


from core.network.port_profile import (
    PortProfile,
)


class RuntimeNetworkProfilesTest(
    unittest.TestCase
):
    def test_every_declared_profile_is_valid(self):
        runtimes = (
            ROOT
            / "catalog"
            / "v2"
            / "runtimes"
        )

        found = 0

        for path in runtimes.rglob(
            "*.json"
        ):
            definition = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            if "network" not in definition:
                continue

            profile = (
                PortProfile.from_mapping(
                    definition["network"]
                )
            )

            self.assertIsNotNone(
                profile,
                path,
            )

            found += 1

        self.assertGreaterEqual(
            found,
            4,
        )


if __name__ == "__main__":
    unittest.main()
