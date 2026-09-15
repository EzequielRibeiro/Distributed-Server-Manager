#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
READER_PATH = ROOT / "agents/linux/privileged/console_journal_reader.py"
CLIENT_PATH = ROOT / "agents/linux/runtime/console_stream_client.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LinuxConsoleStreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reader = load(READER_PATH, "console_journal_reader_tested")
        cls.client = load(CLIENT_PATH, "console_stream_client_tested")

    def test_reader_accepts_only_instance_units(self) -> None:
        event = self.reader._event({
            "_SYSTEMD_UNIT": "capivara-instance-demo-1.service",
            "__CURSOR": "s=cursor",
            "MESSAGE": "\x1b[32mready\x1b[0m",
            "PRIORITY": "6",
        })
        self.assertEqual("demo-1", event["instance_id"])
        self.assertEqual("s=cursor", event["cursor"])
        self.assertIn("\x1b[32m", event["line"])
        self.assertIsNone(self.reader._event({"_SYSTEMD_UNIT": "ssh.service", "MESSAGE": "nope"}))

    def test_client_builds_chunked_authenticated_stream(self) -> None:
        headers = self.client._headers({
            "credential_id": "cred",
            "credential_secret": "secret",
            "fingerprint": "sha256:test",
        })
        self.assertEqual("chunked", headers["Transfer-Encoding"])
        self.assertEqual("application/x-ndjson", headers["Content-Type"])
        self.assertEqual("cred", headers["X-Capivara-Agent-Credential"])
        self.assertEqual("secret", headers["X-Capivara-Agent-Secret"])

    def test_client_frame_is_ndjson_and_bounded(self) -> None:
        raw = self.client._frame_bytes({"kind": "console-batch", "events": [{"line": "ready"}]})
        self.assertTrue(raw.endswith(b"\n"))
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual("console-batch", payload["kind"])

    def test_service_keeps_generic_journal_access_out_of_agent_process(self) -> None:
        agent_service = (ROOT / "agents/linux/services/capivara-agent.service").read_text(encoding="utf-8")
        reader_service = (ROOT / "agents/linux/services/capivara-agent-console-reader.service").read_text(encoding="utf-8")
        self.assertNotIn("systemd-journal", agent_service)
        self.assertIn("User=root", reader_service)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", reader_service)
        self.assertIn("console_journal_reader.py", reader_service)


if __name__ == "__main__":
    unittest.main()
