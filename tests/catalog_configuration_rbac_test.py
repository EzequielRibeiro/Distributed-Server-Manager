#!/usr/bin/env python3

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))


from catalog_configuration_api import (
    read_catalog_file_for_user,
    write_catalog_file_for_user,
)


class CatalogConfigurationRbacTest(unittest.TestCase):
    def test_customer_can_view_but_not_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "catalog" / "v2" / "game.json"
            target.parent.mkdir(parents=True)
            target.write_text(
                '{"name": "game"}\n',
                encoding="utf-8",
            )

            user = {
                "role": "customer",
                "scope_id": "cli-demo",
            }

            result = read_catalog_file_for_user(
                user,
                root,
                "v2/game.json",
            )

            self.assertFalse(result["can_edit"])

            with self.assertRaises(PermissionError):
                write_catalog_file_for_user(
                    user,
                    root,
                    {
                        "path": "v2/game.json",
                        "content": '{"name": "changed"}',
                    },
                )


if __name__ == "__main__":
    unittest.main()
