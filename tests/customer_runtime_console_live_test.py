#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "dashboard", ROOT / "database", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from controller_journal_reader import instance_journal_command
from customer_instance_workspace_http import _console_payload


class CustomerRuntimeConsoleLiveTest(unittest.TestCase):
    def test_instance_journal_unit_is_derived_from_safe_instance_id(self):
        command = instance_journal_command("cli-000001-dayz-001", 400)
        self.assertIn("capivara-instance-cli-000001-dayz-001.service", command)
        self.assertNotIn("--unit", command)
        with self.assertRaises(ValueError):
            instance_journal_command("../../ssh.service", 400)
        with self.assertRaises(ValueError):
            instance_journal_command("x/y", 400)
        with self.assertRaises(ValueError):
            instance_journal_command("", 400)

    def test_customer_console_prefers_live_journal_after_authorized_history_lookup(self):
        class Api:
            def __init__(self):
                self.calls = []

            def console_output(self, user, instance_id, limit):
                self.calls.append((user, instance_id, limit))
                return [{"line": "stored"}]

        api = Api()
        with patch(
            "customer_instance_workspace_http.instance_journal_logs",
            return_value={"logs": ["live one", "live two"], "backend": "systemd-journal"},
        ):
            result = _console_payload(api, {"username": "aurora"}, "cli-000001-dayz-001", 300)

        self.assertEqual(1, len(api.calls))
        self.assertEqual("systemd-journal", result["source"])
        self.assertTrue(result["read_only"])
        self.assertEqual(["live one", "live two"], [item["line"] for item in result["lines"]])

    def test_customer_console_falls_back_to_command_history_when_journal_is_unavailable(self):
        class Api:
            def console_output(self, user, instance_id, limit):
                return [{"line": "stored command result"}]

        with patch(
            "customer_instance_workspace_http.instance_journal_logs",
            return_value={"logs": [], "error": "journal_reader_unavailable"},
        ):
            result = _console_payload(Api(), {"username": "aurora"}, "external-instance", 300)

        self.assertEqual("command-history", result["source"])
        self.assertEqual("stored command result", result["lines"][0]["line"])

    def test_customer_runtime_live_script_applies_stateful_controls_and_console_polling(self):
        script = (ROOT / "dashboard" / "web" / "customer-instance-runtime-live.js").read_text(encoding="utf-8")
        html = (ROOT / "dashboard" / "web" / "customer-instance.html").read_text(encoding="utf-8")
        self.assertIn('["running","online"]', script)
        self.assertIn('start.disabled=', script)
        self.assertIn('restart.disabled=', script)
        self.assertIn('stop.disabled=', script)
        self.assertIn('overview?.console?.supported', script)
        self.assertIn('/console?instance_id=', script)
        self.assertIn('setInterval(refreshConsole,3000)', script)
        self.assertIn('/customer-instance-runtime-live.js', html)


if __name__ == "__main__":
    unittest.main()
