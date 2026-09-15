#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "agents/windows/runtime/console_stream_client.py"


def load_module():
    spec = importlib.util.spec_from_file_location("windows_console_stream_tested", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


STREAM = load_module()


class WindowsConsoleStreamTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.logs = Path(self.temp.name) / "logs"
        self.logs.mkdir()
        self.patch = mock.patch.object(STREAM, "LOG_DIR", self.logs)
        self.patch.start()
        with STREAM._CONDITION:
            STREAM._QUEUE.clear()

    def tearDown(self) -> None:
        self.patch.stop()
        self.temp.cleanup()

    def test_existing_history_is_not_replayed_but_new_lines_are_pushed(self) -> None:
        log = self.logs / "instance-1.log"
        log.write_bytes(b"old line\n")
        states = {}
        self.assertEqual(0, STREAM._scan_logs_once(states))
        with log.open("ab") as handle:
            handle.write(b"\x1b[32mready\x1b[0m\nWARN later\n")
        self.assertEqual(2, STREAM._scan_logs_once(states))
        batch = STREAM._take_batch(0)
        self.assertEqual(2, len(batch))
        self.assertEqual("instance-1", batch[0]["instance_id"])
        self.assertEqual("\x1b[32mready\x1b[0m", batch[0]["line"])
        self.assertTrue(batch[0]["cursor"].startswith("windows:"))

    def test_partial_line_waits_for_terminator(self) -> None:
        log = self.logs / "instance-2.log"
        log.write_bytes(b"")
        states = {}
        STREAM._scan_logs_once(states)
        with log.open("ab") as handle:
            handle.write(b"player con")
        self.assertEqual(0, STREAM._scan_logs_once(states))
        with log.open("ab") as handle:
            handle.write(b"nected\n")
        self.assertEqual(1, STREAM._scan_logs_once(states))
        self.assertEqual("player connected", STREAM._take_batch(0)[0]["line"])

    def test_invalid_log_filename_is_never_forwarded(self) -> None:
        bad = self.logs / "not an instance.log"
        bad.write_text("old\n", encoding="utf-8")
        states = {}
        self.assertEqual(0, STREAM._scan_logs_once(states))
        self.assertNotIn("not an instance", states)

    def test_stream_uses_same_authenticated_chunked_protocol_as_linux(self) -> None:
        headers = STREAM._headers({
            "credential_id": "cred",
            "credential_secret": "secret",
            "fingerprint": "sha256:test",
        })
        self.assertEqual("chunked", headers["Transfer-Encoding"])
        self.assertEqual("application/x-ndjson", headers["Content-Type"])
        self.assertEqual("cred", headers["X-Capivara-Agent-Credential"])
        self.assertEqual("secret", headers["X-Capivara-Agent-Secret"])
        frame = json.loads(STREAM._frame_bytes({"kind": "keepalive"}).decode("utf-8"))
        self.assertEqual("keepalive", frame["kind"])

    def test_agent_and_installer_activate_console_stream_without_extra_service(self) -> None:
        agent = (ROOT / "agents/windows/runtime/agent.py").read_text(encoding="utf-8")
        installer = (ROOT / "agents/windows/installer/install-agent.ps1").read_text(encoding="utf-8")
        self.assertIn("from console_stream_client import start_console_stream", agent)
        self.assertIn("start_console_stream(config)", agent)
        self.assertIn("agent\\runtime\\console_stream_client.py", installer)
        self.assertNotIn("systemd-journal", agent)


if __name__ == "__main__":
    unittest.main()
