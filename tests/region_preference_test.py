#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.placement.region_preference import (
    region_preference_from_payload,
)


class RegionPreferenceTest(unittest.TestCase):
    def test_region_preference(self):
        result = region_preference_from_payload(
            {
                "region_id": "br-sao",
                "allow_cross_region": False,
            }
        )

        self.assertEqual(
            result.region_id,
            "br-sao",
        )
        self.assertFalse(
            result.allow_cross_region
        )

    def test_empty_region_becomes_none(self):
        result = region_preference_from_payload(
            {"region_id": ""}
        )

        self.assertIsNone(
            result.region_id
        )


if __name__ == "__main__":
    unittest.main()
