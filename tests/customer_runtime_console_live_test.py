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
        self.assertEqual(["live one", "live two", "── Respostas de comandos ──", "stored"], [item["line"] for item in result["lines"]])

    def test_customer_console_prefers_fresh_agent_push_before_local_journal_probe(self):
        class Api:
            def console_output(self, user, instance_id, limit):
                return []

        pushed = {
            "lines": [{"line": "remote live", "cursor": "c1"}],
            "source": "agent-push",
            "transport": "persistent-http-chunked",
            "last_seen": "2026-09-15T01:00:00Z",
        }
        with patch("customer_instance_workspace_http.console_push_snapshot", return_value=pushed), \
             patch("customer_instance_workspace_http.instance_journal_logs") as journal:
            result = _console_payload(Api(), {"username": "aurora"}, "remote-instance", 300)
        journal.assert_not_called()
        self.assertEqual("agent-push", result["source"])
        self.assertEqual("remote live", result["lines"][0]["line"])
        self.assertEqual("c1", result["lines"][0]["cursor"])

    def test_customer_console_uses_agent_heartbeat_when_local_journal_is_unavailable(self):
        class Api:
            def console_output(self, user, instance_id, limit):
                return [{"line": "stored command result"}]

            def agent_console_output(self, user, instance_id, limit):
                return {
                    "lines": ["remote one", "remote two"],
                    "transport": "exec",
                    "agent_health": "online",
                    "last_seen": "2026-09-14T23:30:00Z",
                }

        with patch(
            "customer_instance_workspace_http.instance_journal_logs",
            return_value={"logs": [], "error": "journal_reader_unavailable"},
        ):
            result = _console_payload(Api(), {"username": "aurora"}, "external-instance", 300)

        self.assertEqual("agent-heartbeat", result["source"])
        self.assertTrue(result["read_only"])
        self.assertEqual(["remote one", "remote two", "── Respostas de comandos ──", "stored command result"], [item["line"] for item in result["lines"]])
        self.assertEqual("online", result["agent_health"])

    def test_customer_console_falls_back_to_command_history_when_live_sources_are_empty(self):
        class Api:
            def console_output(self, user, instance_id, limit):
                return [{"line": "stored command result"}]

            def agent_console_output(self, user, instance_id, limit):
                return {"lines": [], "agent_health": "offline", "last_seen": "2026-09-14T22:00:00Z"}

        with patch(
            "customer_instance_workspace_http.instance_journal_logs",
            return_value={"logs": [], "error": "journal_reader_unavailable"},
        ):
            result = _console_payload(Api(), {"username": "aurora"}, "external-instance", 300)

        self.assertEqual("command-history", result["source"])
        self.assertEqual("stored command result", result["lines"][0]["line"])
        self.assertEqual("offline", result["agent_health"])

    def test_customer_runtime_live_script_prefers_sse_with_safe_colored_fallback(self):
        script = (ROOT / "dashboard" / "web" / "customer-instance-runtime-live.js").read_text(encoding="utf-8")
        html = (ROOT / "dashboard" / "web" / "customer-instance.html").read_text(encoding="utf-8")
        controller_html = (ROOT / "dashboard" / "web" / "controller-instance.html").read_text(encoding="utf-8")
        css = (ROOT / "dashboard" / "web" / "customer-instance-v2.css").read_text(encoding="utf-8")
        self.assertIn('["running","online"]', script)
        self.assertIn('start.disabled=', script)
        self.assertIn('restart.disabled=', script)
        self.assertIn('stop.disabled=', script)
        self.assertIn('overview?.console?.supported', script)
        self.assertIn('/console?instance_id=', script)
        self.assertIn('new EventSource(url)', script)
        self.assertIn('addEventListener("console-line"', script)
        self.assertIn('appendConsoleLine', script)
        self.assertIn('/console/stream?instance_id=', script)
        self.assertIn('setInterval(refreshConsole,3000)', script)
        self.assertIn('CONSOLE_SAFETY_POLL_MS=3000', script)
        self.assertIn('CONSOLE_SSE_STALE_MS=6000', script)
        self.assertIn('startConsoleSafetyPoll()', script)
        self.assertIn('markConsoleStreamProgress()', script)
        self.assertIn('source==="agent-heartbeat"', script)
        self.assertIn('Tempo real · SSE', script)
        self.assertIn('Fallback · 3 s', script)
        self.assertIn('document.createTextNode', script)
        self.assertIn('ansi-fg-31', css)
        self.assertIn('level-error', css)
        self.assertIn('id="console-live-status"', html)
        self.assertIn('id="console-live-status"', controller_html)
        self.assertNotIn('id="console-history-panel"', html)
        self.assertNotIn('id="console-history-summary"', html)
        self.assertNotIn('Exibir histórico de comandos', html)
        self.assertNotIn('id="console-history-panel"', controller_html)
        self.assertIn('liveItems=items.filter', script)
        self.assertIn('!=="command-history"', script)
        self.assertIn('String(data?.source||"")==="command-history"', script)
        self.assertNotIn('console-history', css)
        self.assertIn('#console-live-status.warn', css)
        self.assertIn('/customer-instance-runtime-live.js', html)
        core = (ROOT / "dashboard" / "web" / "customer-instance-v2.js").read_text(encoding="utf-8")
        self.assertIn('/console/status?instance_id=', core)
        self.assertIn('Falha no comando:', core)
        self.assertIn('aguardando execução', core)


if __name__ == "__main__":
    unittest.main()
