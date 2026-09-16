#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "agents" / "common"
if str(COMMON) not in sys.path:
    sys.path.insert(0, str(COMMON))

from dayz_native_maintenance import (
    DayZNativeMaintenanceError,
    MANAGED_TEXT,
    plan,
    render_messages_xml,
    resolve_mission,
)


class DayZNativeMaintenanceTest(unittest.TestCase):
    def _record(self, root: Path, *, arguments=None) -> dict:
        return {
            "instance_id": "dayz-001",
            "agent_id": "agent-001",
            "game_id": "dayz",
            "working_directory": str(root),
            "arguments": list(arguments or ["-config=serverDZ.cfg"]),
        }

    def test_resolves_mission_from_agent_owned_server_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "serverDZ.cfg").write_text(
                'hostname = "Test";\nclass Missions { class DayZ { template = "dayzOffline.chernarusplus"; }; };\n',
                encoding="utf-8",
            )
            mission, mission_root = resolve_mission(self._record(root))
            self.assertEqual(mission, "dayzOffline.chernarusplus")
            self.assertEqual(mission_root, (root / "mpmissions" / mission).resolve())

    def test_mission_launch_argument_is_authoritative(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mission_path = root / "mpmissions" / "dayzOffline.enoch"
            mission, resolved = resolve_mission(
                self._record(root, arguments=[f"-mission={mission_path}", "-config=serverDZ.cfg"])
            )
            self.assertEqual(mission, "dayzOffline.enoch")
            self.assertEqual(resolved, mission_path.resolve())

    def test_rejects_mission_path_outside_instance_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(DayZNativeMaintenanceError, "outside instance root"):
                resolve_mission(self._record(root, arguments=["-mission=../foreign/dayzOffline.enoch"]))

    def test_rejects_non_dayz_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = self._record(Path(temporary))
            record["game_id"] = "minecraft"
            with self.assertRaisesRegex(DayZNativeMaintenanceError, "game_id=dayz"):
                resolve_mission(record)

    def test_render_preserves_existing_messages_and_replaces_only_capivara_entry(self):
        existing = """<?xml version="1.0" encoding="UTF-8"?>
<messages>
  <message><delay>5</delay><repeat>30</repeat><deadline>0</deadline><onConnect>1</onConnect><shutdown>0</shutdown><text>Community notice</text></message>
  <message><delay>0</delay><repeat>0</repeat><deadline>5</deadline><onConnect>0</onConnect><shutdown>1</shutdown><text>Capivara maintenance: #name will restart in #tmin minutes.</text></message>
</messages>
"""
        rendered = render_messages_xml(existing, 120)
        root = ET.fromstring(rendered)
        texts = [str(node.findtext("text") or "") for node in root.findall("message")]
        self.assertEqual(texts.count("Community notice"), 1)
        self.assertEqual(texts.count(MANAGED_TEXT), 1)
        managed = next(node for node in root.findall("message") if node.findtext("text") == MANAGED_TEXT)
        self.assertEqual(managed.findtext("deadline"), "120")
        self.assertEqual(managed.findtext("shutdown"), "1")

    def test_invalid_existing_xml_fails_closed(self):
        with self.assertRaisesRegex(DayZNativeMaintenanceError, "invalid"):
            render_messages_xml("<messages><message>", 60)

    def test_deadline_is_bounded(self):
        for invalid in (0, -1, 10081):
            with self.subTest(invalid=invalid):
                with self.assertRaises(DayZNativeMaintenanceError):
                    render_messages_xml(None, invalid)

    def test_plan_targets_only_mission_db_messages_xml(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mission = root / "mpmissions" / "dayzOffline.chernarusplus"
            mission.mkdir(parents=True)
            (root / "serverDZ.cfg").write_text(
                'class Missions { class DayZ { template="dayzOffline.chernarusplus"; }; };\n',
                encoding="utf-8",
            )
            result = plan(self._record(root), 90)
            self.assertEqual(result.messages_path, str((mission / "db" / "messages.xml").resolve()))
            self.assertEqual(result.deadline_minutes, 90)
            self.assertIn("<shutdown>1</shutdown>", result.xml)
            self.assertIn(MANAGED_TEXT, result.xml)


if __name__ == "__main__":
    unittest.main()
