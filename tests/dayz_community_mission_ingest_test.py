#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "agents" / "common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from dayz_community_missions import (
    DayZCommunityMissionError,
    community_mission_manifest,
    discover_community_missions,
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DayZCommunityMissionIngestTest(unittest.TestCase):
    def _mission(self, root: Path, name: str) -> Path:
        mission = root / "Mission Files" / name
        (mission / "db").mkdir(parents=True)
        (mission / "init.c").write_text("void main() {}\n", encoding="utf-8")
        (mission / "cfgeconomycore.xml").write_text("<economycore/>\n", encoding="utf-8")
        (mission / "db" / "types.xml").write_text("<types/>\n", encoding="utf-8")
        return mission

    def test_discovers_namalsk_style_regular_and_hardcore_missions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._mission(root, "regular.namalsk")
            self._mission(root, "hardcore.namalsk")
            (root / "Server Config" / "Regular").mkdir(parents=True)
            (root / "Server Config" / "Regular" / "serverDZ.cfg").write_text(
                'template="regular.namalsk";\n',
                encoding="utf-8",
            )

            manifest = community_mission_manifest(root)

            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["kind"], "CapivaraDayZCommunityMissionManifest")
            self.assertEqual(manifest["count"], 2)
            self.assertEqual(
                [item["id"] for item in manifest["missions"]],
                ["hardcore.namalsk", "regular.namalsk"],
            )
            self.assertEqual(
                [item["relative_path"] for item in manifest["missions"]],
                [
                    "Mission Files/hardcore.namalsk",
                    "Mission Files/regular.namalsk",
                ],
            )

    def test_rejects_payload_without_recognizable_mission(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "README.md").write_text("not a mission\n", encoding="utf-8")
            with self.assertRaisesRegex(
                DayZCommunityMissionError,
                "no recognizable mission",
            ):
                discover_community_missions(root)

    def test_requires_dayz_mission_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fake = root / "Mission Files" / "regular.namalsk"
            fake.mkdir(parents=True)
            (fake / "init.c").write_text("void main() {}\n", encoding="utf-8")
            with self.assertRaises(DayZCommunityMissionError):
                discover_community_missions(root)

    def test_linux_and_windows_semantic_validation_inspect_remote_dayz_maps(self) -> None:
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self._mission(root, "regular.namalsk")
                module = _load(
                    ROOT / "agents" / platform / "runtime" / "content_semantic_validation.py",
                    f"dayz_map_semantic_{platform}_{id(self)}",
                )
                result = module.validate_external_content_payload(
                    root,
                    {
                        "game_id": "dayz",
                        "content_type": "map",
                        "provider": "github",
                        "artifact": {
                            "provider": "github",
                            "url": "https://example.invalid/namalsk.zip",
                            "archive": True,
                        },
                    },
                )
                self.assertEqual(result["validator"], "dayz-community-map-v1")
                self.assertEqual(result["mission_count"], 1)
                self.assertEqual(result["missions"][0]["id"], "regular.namalsk")


if __name__ == "__main__":
    unittest.main()
