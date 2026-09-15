#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard", ROOT / "database", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from customer_instance_workspace_http import (
    ROUTES,
    _console_stream_signature,
    _serve_console_stream,
    _sse_frame,
)


class CustomerConsoleStreamTest(unittest.TestCase):
    def test_console_stream_route_is_registered(self) -> None:
        self.assertIn("/api/customer/instance/workspace/console/stream", ROUTES)

    def test_stream_signature_changes_only_with_visible_console_state(self) -> None:
        first = {"lines": [{"line": "ready"}], "source": "systemd-journal", "ignored": "a"}
        same = {"lines": [{"line": "ready"}], "source": "systemd-journal", "ignored": "b"}
        changed = {"lines": [{"line": "player joined"}], "source": "systemd-journal"}
        self.assertEqual(_console_stream_signature(first), _console_stream_signature(same))
        self.assertNotEqual(_console_stream_signature(first), _console_stream_signature(changed))

    def test_stream_sends_ready_and_changed_snapshot_with_sse_headers(self) -> None:
        class Api:
            def console_output(self, user, instance_id, limit):
                return []

            def agent_console_output(self, user, instance_id, limit):
                return {}

        class Handler:
            def __init__(self):
                self.wfile = io.BytesIO()
                self.headers = {}
                self.status = None
                self.sent_headers = {}

            def send_response(self, status):
                self.status = status

            def send_header(self, name, value):
                self.sent_headers[name] = value

            def end_headers(self):
                pass

        handler = Handler()
        with patch("customer_instance_workspace_http.instance_journal_logs", return_value={"logs": ["\x1b[32mready\x1b[0m"]}), \
             patch("customer_instance_workspace_http.time.monotonic", side_effect=[0, 0.1, 0.2, 0.3, 6]), \
             patch("customer_instance_workspace_http.time.sleep", return_value=None):
            _serve_console_stream(handler, Api(), {"username": "aurora"}, "demo", 100, timeout=1)
        body = handler.wfile.getvalue().decode("utf-8")
        self.assertEqual(200, handler.status)
        self.assertEqual("text/event-stream; charset=utf-8", handler.sent_headers["Content-Type"])
        self.assertEqual("no", handler.sent_headers["X-Accel-Buffering"])
        self.assertIn("event: ready", body)
        self.assertIn("event: console-snapshot", body)
        self.assertIn("\\u001b[32mready", body)

    def test_sse_frame_is_json_and_never_html(self) -> None:
        frame = _sse_frame(
            "console-snapshot",
            {"lines": [{"line": "<script>alert(1)</script>\u001b[31mERROR\u001b[0m"}]},
            event_id="cursor-1",
        ).decode("utf-8")
        self.assertIn("id: cursor-1", frame)
        self.assertIn("event: console-snapshot", frame)
        data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line[6:])
        self.assertEqual("<script>alert(1)</script>\u001b[31mERROR\u001b[0m", payload["lines"][0]["line"])


if __name__ == "__main__":
    unittest.main()
