"""#928: isolated execution of the actual Agent run_forever scheduler.

This is NOT a full Controller daemon, a real Agent host inventory, or a
no-drain update. All host-mutating startup hooks are replaced with fail-closed
guards; the loop and its error/retry behavior are real.
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
import agent as linux_agent


class StopFixture(Exception):
    pass


class AgentRunForeverLoopTests(unittest.TestCase):
    def test_scheduler_recovers_after_heartbeat_failure_without_host_operations(self):
        config = {
            "agent_id": "dsm928-fixture-agent",
            "credential_id": "fixture-id",
            "credential_secret": "fixture-secret",
            "heartbeat_interval_seconds": 10,
            "reconcile_interval_seconds": 5,
        }
        calls = []
        clock = [100.0]
        heartbeat_attempts = [0]

        def forbidden(*_args, **_kwargs):
            raise AssertionError("unexpected host operation in #928 fixture")

        def heartbeat(_config):
            heartbeat_attempts[0] += 1
            calls.append("heartbeat")
            if heartbeat_attempts[0] == 1:
                raise ConnectionError("disposable Controller temporarily unavailable")
            return {"agent_id": config["agent_id"], "health_status": "online", "status": "active"}

        def reconcile(_config):
            calls.append("reconcile")

        def sleep(_seconds):
            clock[0] += 11.0
            if heartbeat_attempts[0] >= 2:
                raise StopFixture()

        with ExitStack() as stack:
            stack.enter_context(patch.object(linux_agent, "_load_config", return_value=config))
            stack.enter_context(patch.object(linux_agent, "enroll", side_effect=forbidden))
            stack.enter_context(patch.object(linux_agent, "recover_interrupted_operations", return_value=[]))
            stack.enter_context(patch.object(linux_agent, "start_console_stream", return_value=None))
            stack.enter_context(patch.object(linux_agent, "start_content_update_inventory", return_value=None))
            stack.enter_context(patch.object(linux_agent, "FinalizationWorkerSupervisor", return_value=object()))
            stack.enter_context(patch.object(linux_agent, "reconcile_all", side_effect=reconcile))
            stack.enter_context(patch.object(linux_agent, "heartbeat", side_effect=heartbeat))
            stack.enter_context(patch.object(linux_agent.time, "monotonic", side_effect=lambda: clock[0]))
            stack.enter_context(patch.object(linux_agent.time, "sleep", side_effect=sleep))
            stack.enter_context(patch.object(linux_agent, "_log", return_value=None))
            for name in (
                "CAPIVARA_SERVERPACK_FINALIZATION_AUDIT",
                "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE",
                "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER",
                "CAPIVARA_SERVERPACK_FINALIZATION_RECOVER_ACK",
                "CAPIVARA_SERVERPACK_FINALIZATION_RECONCILE_INSTANCE",
            ):
                stack.enter_context(patch.dict(linux_agent.os.environ, {name: ""}))
            with self.assertRaises(StopFixture):
                linux_agent.run_forever()

        self.assertEqual(heartbeat_attempts[0], 2)
        self.assertEqual(calls, ["reconcile", "heartbeat", "reconcile", "heartbeat"])


if __name__ == "__main__":
    unittest.main()
