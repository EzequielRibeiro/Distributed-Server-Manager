#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for item in (
    ROOT,
    ROOT / "agents" / "common",
    ROOT / "agents" / "linux" / "runtime",
):
    value = str(item)
    if value not in sys.path:
        sys.path.insert(0, value)

import dayz_native_restart_client as client


class DayZNativeRestartClientTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        self.state = self.root / "state"
        self.instance_root = self.root / "instance"
        self.mission = self.instance_root / "mpmissions" / "dayzOffline.chernarusplus"
        self.db = self.mission / "db"

        self.db.mkdir(parents=True)
        self.instance_root.mkdir(parents=True, exist_ok=True)

        (self.instance_root / "serverDZ.cfg").write_text(
            'class Missions { class DayZ { template="dayzOffline.chernarusplus"; }; };\n',
            encoding="utf-8",
        )

        self.record = {
            "instance_id": "dayz-001",
            "agent_id": "agent-001",
            "game_id": "dayz",
            "working_directory": str(self.instance_root),
            "arguments": ["-config=serverDZ.cfg"],
        }

        self.config = {
            "agent_id": "agent-001",
        }

        self.old_state = client.STATE_DIR
        self.old_result = client.RESULT_DIR
        self.old_history = client.HISTORY_DIR

        client.STATE_DIR = self.state
        client.RESULT_DIR = self.state / "dayz-native-restart-results"
        client.HISTORY_DIR = self.state / "dayz-native-restart-history"

    def tearDown(self):
        client.STATE_DIR = self.old_state
        client.RESULT_DIR = self.old_result
        client.HISTORY_DIR = self.old_history
        self.temp.cleanup()

    def command(self):
        due = datetime.now(timezone.utc) + timedelta(minutes=5)
        return {
            "command_id": "dayz-maint-test",
            "instance_id": "dayz-001",
            "due_at": due.isoformat().replace("+00:00", "Z"),
        }

    def test_materializes_messages_xml(self):
        with patch.object(client, "get_instance", return_value=self.record):
            result = client.handle_command(self.config, self.command())

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["instance_id"], "dayz-001")

        target = self.db / "messages.xml"
        self.assertTrue(target.is_file())

        xml = target.read_text(encoding="utf-8")
        self.assertIn("<shutdown>1</shutdown>", xml)
        self.assertIn("Capivara maintenance:", xml)

    def test_result_is_idempotent(self):
        command = self.command()

        with patch.object(client, "get_instance", return_value=self.record):
            first = client.handle_command(self.config, command)
            second = client.handle_command(self.config, command)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "completed")

    def test_rejects_instance_owned_by_another_agent(self):
        record = dict(self.record)
        record["agent_id"] = "agent-other"

        with patch.object(client, "get_instance", return_value=record):
            result = client.handle_command(self.config, self.command())

        self.assertEqual(result["status"], "failed")
        self.assertIn("another Agent", result["error"])

    def test_rejects_non_dayz_instance(self):
        record = dict(self.record)
        record["game_id"] = "minecraft"

        with patch.object(client, "get_instance", return_value=record):
            result = client.handle_command(self.config, self.command())

        self.assertEqual(result["status"], "failed")
        self.assertIn("requires DayZ", result["error"])

    def test_rejects_past_due_at(self):
        command = self.command()
        command["due_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat().replace("+00:00", "Z")

        with patch.object(client, "get_instance", return_value=self.record):
            result = client.handle_command(self.config, command)

        self.assertEqual(result["status"], "failed")
        self.assertIn("future", result["error"])

    def test_read_and_clear_result(self):
        command = self.command()

        with patch.object(client, "get_instance", return_value=self.record):
            created = client.handle_command(self.config, command)

        read = client.read_result()
        self.assertEqual(read["command_id"], created["command_id"])

        client.clear_result(created["command_id"])

        self.assertIsNone(client.read_result())


if __name__ == "__main__":
    unittest.main()
