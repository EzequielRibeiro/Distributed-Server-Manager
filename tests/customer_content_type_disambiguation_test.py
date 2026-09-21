#!/usr/bin/env python3
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

FILES = (
    ROOT / "dashboard" / "web" / "customer-instance-v2.js",
    ROOT / "dashboard" / "web" / "controller-instance-core.js",
)


class CustomerContentTypeDisambiguationTest(unittest.TestCase):
    def test_content_type_requires_explicit_selection(self):
        for path in FILES:
            with self.subTest(path=path.name):
                script = path.read_text(encoding="utf-8")

                self.assertIn(
                    'type.append(new Option("Selecione o tipo…",""))',
                    script,
                )
                self.assertIn('type.value=""', script)

    def test_install_preserves_discovered_content_type(self):
        for path in FILES:
            with self.subTest(path=path.name):
                script = path.read_text(encoding="utf-8")

                self.assertIn(
                    "content_type:item.content_type",
                    script,
                )

    def test_search_result_exposes_loader_family(self):
        for path in FILES:
            with self.subTest(path=path.name):
                script = path.read_text(encoding="utf-8")

                self.assertIn(
                    'item.content_type==="plugin"?"Bukkit/Spigot"',
                    script,
                )
                self.assertIn(
                    'item.content_type==="mod"?"NeoForge"',
                    script,
                )


if __name__ == "__main__":
    unittest.main()
