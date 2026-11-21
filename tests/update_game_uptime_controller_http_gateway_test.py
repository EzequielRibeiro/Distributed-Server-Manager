"""One grouped #928 proof: final HTTP mutation gate after full composition.

Isolated handler class and real temporary kernel flock. No DSM daemon,
external Agent, game, database, updater or system service is accessed.
"""
from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "dashboard", ROOT / "agents/linux/runtime"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import game_uptime_controller_mutation_gate as gate
from game_uptime_controller_agent_http_flock import (
    shared_controller_agent_http_lock,
    exclusive_controller_agent_http_lock,
    ControllerHttpLockUnavailable,
)
from prepare_controller_agent_http_lock import provision_controller_agent_http_lock


class ControllerHttpGatewayTests(unittest.TestCase):
    def test_all_mutating_verbs_share_single_fence_while_observer_remains_readonly(self):
        class FakeHandler:
            calls = []
            responses = []
            waiting = None
            proceed = None

            def __init__(self, path):
                self.path = path
                self.calls = []
                self.responses = []

            def send_json(self, code, value):
                self.responses.append((code, value))

            def _execute(self, method):
                self.calls.append(method)
                if self.path == "/api/admin/long-operation":
                    self.waiting.set()
                    if not self.proceed.wait(timeout=10):
                        raise RuntimeError("HTTP test operation exceeded deadline")
                self.send_json(200, {"status": method})

            def do_POST(self):
                return self._execute("POST")

            def do_PUT(self):
                return self._execute("PUT")

            def do_PATCH(self):
                return self._execute("PATCH")

            def do_DELETE(self):
                return self._execute("DELETE")

            def do_GET(self):
                return self._execute("GET")

        with tempfile.TemporaryDirectory(prefix="dsm928-all-http-") as directory:
            parent = Path(directory) / "fence"
            parent.mkdir(mode=0o755)
            witness = parent / "controller-agent-http.lock"
            uid, gid = os.geteuid(), os.getegid()
            provision_controller_agent_http_lock(uid, gid, path=witness,
                                                 parent_uid=uid)

            def shared():
                return shared_controller_agent_http_lock(
                    lock_path=witness, expected_uid=uid, expected_gid=gid,
                    parent_uid=uid, enabled=True)

            def exclusive():
                return exclusive_controller_agent_http_lock(
                    lock_path=witness, expected_uid=uid, expected_gid=gid,
                    parent_uid=uid)

            class Legacy:
                DashboardHandler = FakeHandler

            gate.install_controller_mutation_gate(Legacy)
            gate.install_controller_mutation_gate(Legacy)  # one wrapper per verb

            with patch.object(gate, "shared_controller_agent_http_lock",
                              side_effect=shared):
                for evidence in ({"active": True}, {"active": "unknown"}, None):
                    with patch.object(gate, "observe_no_drain_hold",
                                      return_value=evidence):
                        for verb in ("POST", "PUT", "PATCH", "DELETE"):
                            obj = FakeHandler("/api/admin/mutating")
                            getattr(obj, "do_" + verb)()
                            self.assertEqual(obj.calls, [])
                            self.assertEqual(obj.responses[-1][0], 423)
                            self.assertFalse(
                                obj.responses[-1][1]["live_no_drain_authorized"])

                with patch.object(gate, "observe_no_drain_hold",
                                  side_effect=OSError("hold unavailable")):
                    obj = FakeHandler("/api/admin/mutating")
                    obj.do_POST()
                    self.assertEqual(obj.responses[-1][0], 423)

                with patch.object(gate, "observe_no_drain_hold",
                                  return_value={"active": True}):
                    observer = FakeHandler("/api/agent/no-drain/observe?probe=1")
                    observer.do_POST()
                    self.assertEqual(observer.calls, ["POST"])
                    self.assertEqual(observer.responses[-1][0], 200)

                    get = FakeHandler("/api/health")
                    get.do_GET()
                    self.assertEqual(get.calls, ["GET"])

                with patch.object(gate, "observe_no_drain_hold",
                                  return_value={"active": False}):
                    with exclusive() as evidence:
                        self.assertFalse(evidence["controller_http_acked"])
                        obj = FakeHandler("/api/admin/mutating")
                        obj.do_POST()
                        self.assertEqual(obj.responses[-1][0], 423)
                        self.assertEqual(
                            obj.responses[-1][1]["reason"],
                            "controller_http_interprocess_fence_unavailable")
                        self.assertEqual(obj.calls, [])

                    for verb in ("POST", "PUT", "PATCH", "DELETE"):
                        obj = FakeHandler("/api/admin/mutating")
                        getattr(obj, "do_" + verb)()
                        self.assertEqual(obj.calls, [verb])
                        self.assertEqual(obj.responses[-1][0], 200)

                    # Work already admitted prevents a new exclusive fence.
                    waiting, proceed = threading.Event(), threading.Event()
                    obj = FakeHandler("/api/admin/long-operation")
                    obj.waiting, obj.proceed = waiting, proceed
                    failures = []

                    def invoke():
                        try:
                            obj.do_POST()
                        except BaseException as exc:
                            failures.append(exc)

                    thread = threading.Thread(target=invoke, daemon=True)
                    try:
                        thread.start()
                        self.assertTrue(waiting.wait(timeout=10))
                        with self.assertRaises(ControllerHttpLockUnavailable):
                            with exclusive():
                                self.fail("EX must reject live HTTP call")
                    finally:
                        proceed.set()
                        thread.join(timeout=10)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(failures, [])
                    self.assertEqual(obj.calls, ["POST"])
                    with exclusive() as evidence:
                        self.assertFalse(evidence["live_no_drain_authorized"])

        # The top-level production entrypoint installs AFTER its other wrappers.
        source = (ROOT / "dashboard/server_part22.py").read_text(encoding="utf-8")
        self.assertGreater(
            source.index("install_controller_mutation_gate(legacy)"),
            source.index("install_curseforge_provider_http(legacy, _controller_authenticate)"))


if __name__ == "__main__":
    unittest.main()
