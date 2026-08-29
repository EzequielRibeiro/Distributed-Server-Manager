#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from catalog_resource_profiles_http import save_catalog_resource_profiles


class GameProfilePresentationTest(unittest.TestCase):
    def _root(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "catalog" / "v2" / "games" / "dayz").mkdir(parents=True)
        return temporary, root

    def test_presentation_is_sanitized_before_persistence(self):
        temporary, root = self._root()
        self.addCleanup(temporary.cleanup)
        payload = save_catalog_resource_profiles(root, "dayz", [{
            "id": "survival",
            "name": "Survival",
            "description": "Servidor de sobrevivência",
            "memory_mb": 8192,
            "storage_mb": 51200,
            "cpu_cores": 4,
            "swap_mb": 1024,
            "pids_limit": 512,
            "presentation": {
                "theme_id": "survival",
                "html": '<section onclick="alert(1)"><h2>{{profile.name}}</h2><script>alert(1)</script><img src="https://evil.invalid/x.png"></section>',
                "css": ".card{color:#fff}",
                "assets": [],
            },
        }], "survival")
        presentation = payload["profiles"][0]["presentation"]
        self.assertEqual(presentation["theme_id"], "survival")
        self.assertIn("{{profile.name}}", presentation["html"])
        self.assertNotIn("onclick", presentation["html"])
        self.assertNotIn("<script", presentation["html"])
        self.assertNotIn("https://evil.invalid", presentation["html"])

    def test_unsafe_css_is_rejected(self):
        temporary, root = self._root()
        self.addCleanup(temporary.cleanup)
        with self.assertRaises(ValueError):
            save_catalog_resource_profiles(root, "dayz", [{
                "id": "survival",
                "name": "Survival",
                "memory_mb": 4096,
                "storage_mb": 20480,
                "cpu_cores": 2,
                "presentation": {"html": "<section>ok</section>", "css": "@import url(https://evil.invalid/x.css);"},
            }])

    def test_editor_exposes_preview_and_seed_themes(self):
        html = (ROOT / "dashboard" / "web" / "game-profiles.html").read_text(encoding="utf-8")
        editor = (ROOT / "dashboard" / "web" / "game-profile-presentation.js").read_text(encoding="utf-8")
        self.assertIn("/game-profile-presentation.js?v=1", html)
        self.assertIn("data-profile-preview", editor)
        self.assertIn("iframe sandbox", editor)
        for theme in ("Survival", "Tactical", "Blocks", "Industrial", "Minimal Dark"):
            self.assertIn(theme, editor)

    def test_customer_renderer_uses_sandboxed_iframe(self):
        source = (ROOT / "dashboard" / "web" / "contract-demo.js").read_text(encoding="utf-8")
        self.assertIn("renderedPresentation", source)
        self.assertIn('frame.sandbox=""', source)
        self.assertIn("profile.presentation", source)


if __name__ == "__main__":
    unittest.main()
