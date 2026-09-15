#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "dashboard", ROOT / "database", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import agent_console_push as PUSH


class AgentConsolePushTest(unittest.TestCase):
    def setUp(self) -> None:
        with PUSH._LOCK:
            PUSH._BUFFERS.clear()
            PUSH._AGENT_SEEN.clear()
            PUSH._OWNERSHIP_CACHE.clear()

    def test_ingest_deduplicates_cursor_and_preserves_ansi(self) -> None:
        event = {"instance_id": "instance-1", "cursor": "c1", "line": "\x1b[31mERROR\x1b[0m"}
        with patch.object(PUSH, "_owned_instances", return_value={"instance-1"}):
            first = PUSH.ingest_console_events("agent-1", [event], backend=object())
            second = PUSH.ingest_console_events("agent-1", [event], backend=object())
        self.assertEqual(1, first["accepted"])
        self.assertEqual(1, second["duplicates"])
        snapshot = PUSH.console_push_snapshot("instance-1")
        self.assertEqual("agent-push", snapshot["source"])
        self.assertEqual("\x1b[31mERROR\x1b[0m", snapshot["lines"][0]["line"])

    def test_waiter_observes_new_generation_without_polling(self) -> None:
        event = {"instance_id": "instance-1", "cursor": "c1", "line": "ready"}
        with patch.object(PUSH, "_owned_instances", return_value={"instance-1"}):
            PUSH.ingest_console_events("agent-1", [event], backend=object())
        snapshot = PUSH.wait_for_console_push("instance-1", 0, timeout=0.05)
        self.assertIsNotNone(snapshot)
        self.assertEqual(1, snapshot["generation"])
        self.assertEqual("c1", snapshot["lines"][-1]["cursor"])

    def test_ownership_lookup_is_short_lived_cached(self) -> None:
        class Repo:
            calls = 0
            def __init__(self, backend):
                pass
            def initialize(self):
                pass
            def instance_context(self, instance_id):
                Repo.calls += 1
                return {"agent_id": "agent-1"}

        with patch.object(PUSH, "InstanceWorkspaceRepository", Repo), \
             patch.object(PUSH.time, "monotonic", side_effect=[100.0, 100.1, 103.0]):
            self.assertEqual({"instance-1"}, PUSH._owned_instances("agent-1", {"instance-1"}, object()))
            self.assertEqual({"instance-1"}, PUSH._owned_instances("agent-1", {"instance-1"}, object()))
            self.assertEqual({"instance-1"}, PUSH._owned_instances("agent-1", {"instance-1"}, object()))
        self.assertEqual(2, Repo.calls)

    def test_chunked_stream_accepts_microbatch(self) -> None:
        payload = json.dumps({
            "kind": "console-batch",
            "events": [{"instance_id": "instance-1", "cursor": "cursor-2", "line": "ready"}],
        }, separators=(",", ":")).encode() + b"\n"
        wire = f"{len(payload):X}\r\n".encode() + payload + b"\r\n0\r\n\r\n"

        class Connection:
            def settimeout(self, value):
                self.timeout = value

        class Handler:
            def __init__(self):
                self.rfile = io.BytesIO(wire)
                self.connection = Connection()
                self.responses = []

            def send_json(self, status, body):
                self.responses.append((status, body))

        handler = Handler()
        with patch.object(PUSH, "_authenticate", return_value={"agent_id": "agent-1"}), \
             patch.object(PUSH, "_owned_instances", return_value={"instance-1"}):
            PUSH.serve_agent_console_stream(
                handler,
                headers={"Transfer-Encoding": "chunked", "Content-Type": "application/x-ndjson"},
                backend=object(),
            )
        self.assertEqual(200, handler.responses[-1][0])
        self.assertEqual(1, handler.responses[-1][1]["accepted"])
        self.assertEqual("ready", PUSH.console_push_snapshot("instance-1")["lines"][0]["line"])

    def test_rejects_instance_not_owned_by_authenticated_agent(self) -> None:
        with patch.object(PUSH, "_owned_instances", return_value=set()):
            result = PUSH.ingest_console_events(
                "agent-1",
                [{"instance_id": "other-agent-instance", "cursor": "c", "line": "secret"}],
                backend=object(),
            )
        self.assertEqual(0, result["accepted"])
        self.assertEqual(1, result["rejected"])
        self.assertIsNone(PUSH.console_push_snapshot("other-agent-instance"))


if __name__ == "__main__":
    unittest.main()
