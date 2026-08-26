#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "core", ROOT / "database", ROOT / "dashboard", ROOT / "agents" / "linux" / "runtime"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_heartbeat_api import record_agent_heartbeat
from backend import DatabaseConfig
from backend_factory import create_backend
from event_platform import EventValidationError, normalize_event, runtime_event_to_universal
from runtime_events import acknowledge_runtime_events, emit_runtime_event, read_runtime_events
from universal_event_repository import UniversalEventRepository


class UniversalEventContractTest(unittest.TestCase):
    def test_normalizes_canonical_envelope(self):
        event = normalize_event({
            "event_type": "instance_started",
            "source": "controller.test",
            "severity": "INFO",
            "data": {"value": 1},
        })
        self.assertEqual(event["kind"], "CapivaraUniversalEvent")
        self.assertEqual(event["event_type"], "INSTANCE_STARTED")
        self.assertEqual(event["severity"], "info")
        self.assertEqual(event["data"], {"value": 1})
        self.assertTrue(event["event_id"])

    def test_rejects_invalid_event_type_and_severity(self):
        with self.assertRaises(EventValidationError):
            normalize_event({"event_type": "bad type", "source": "test"})
        with self.assertRaises(EventValidationError):
            normalize_event({"event_type": "VALID_TYPE", "source": "test", "severity": "fatal"})

    def test_binds_canonical_runtime_event_to_authenticated_agent(self):
        raw = {
            "schema_version": 1,
            "kind": "CapivaraRuntimeEvent",
            "event_id": "runtime-event-1",
            "event_type": "INSTANCE_DRIFT_DETECTED",
            "occurred_at": "2026-08-21T12:00:00Z",
            "agent_id": "agent-c1",
            "instance_id": "instance-c1",
            "data": {"reason": "stopped"},
        }
        event = runtime_event_to_universal(raw, authenticated_agent_id="agent-c1")
        self.assertEqual(event["event_id"], "runtime-event-1")
        self.assertEqual(event["source"], "agent.runtime")
        self.assertEqual(event["event_type"], "INSTANCE_DRIFT_DETECTED")

    def test_runtime_event_rejects_noncanonical_record(self):
        with self.assertRaises(EventValidationError):
            runtime_event_to_universal({
                "kind": "CapivaraEvent",
                "type": "INSTANCE_DRIFT_DETECTED",
                "agent_id": "agent-c1",
            }, authenticated_agent_id="agent-c1")


class UniversalEventRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.temp.name) / "capivara.db"),
        ))
        self.backend.initialize()
        self.customer_id = 1
        with self.backend.transaction() as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                ("controller-node-c1", "Controller Node", "controller", "active"),
            )
            connection.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                ("agent-node-c1", "Agent Node", "agent", "active"),
            )
            connection.execute(
                "INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)",
                ("agent-node-other", "Other Agent Node", "agent", "active"),
            )
            connection.execute(
                "INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
                ("controller-c1", "controller-node-c1", "C1", "active"),
            )
            connection.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                ("agent-c1", "controller-c1", "agent-node-c1", "Agent", "active"),
            )
            connection.execute(
                "INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                ("agent-other", "controller-c1", "agent-node-other", "Other", "active"),
            )
            connection.execute(
                "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                (self.customer_id, "controller-c1", "Customer", "active"),
            )
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                ("instance-c1", "agent-node-c1", "minecraft", "minecraft.bedrock.vanilla", "C1", "online", "controller-c1", "agent-c1", self.customer_id),
            )
        self.repo = UniversalEventRepository(self.backend)
        self.repo.initialize()

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def runtime_event(self, event_id="event-c1", **extra):
        value = {
            "schema_version": 1,
            "kind": "CapivaraRuntimeEvent",
            "event_id": event_id,
            "event_type": "INSTANCE_RECOVERED",
            "occurred_at": "2026-08-21T12:01:00Z",
            "agent_id": "agent-c1",
            "instance_id": "instance-c1",
            "data": {"attempt": 1},
        }
        value.update(extra)
        return value

    def test_publish_is_idempotent_and_filterable(self):
        event = normalize_event({
            "event_id": "controller-event",
            "event_type": "PLACEMENT_SELECTED",
            "source": "controller.placement",
            "severity": "info",
            "instance_id": "instance-c1",
            "data": {"agent_id": "agent-c1"},
        })
        first = self.repo.publish(event)
        second = self.repo.publish(event)
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        rows = self.repo.list_events(event_type="PLACEMENT_SELECTED", instance_id="instance-c1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_id"], "controller-event")

    def test_agent_ingestion_is_idempotent_and_acks_duplicates(self):
        result1 = self.repo.ingest_agent_events("agent-c1", [self.runtime_event()])
        result2 = self.repo.ingest_agent_events("agent-c1", [self.runtime_event()])
        self.assertEqual(result1["created"], 1)
        self.assertEqual(result2["created"], 0)
        self.assertEqual(result2["accepted_event_ids"], ["event-c1"])
        self.assertEqual(len(self.repo.list_events(agent_id="agent-c1")), 1)

    def test_agent_ingestion_rejects_identity_and_ownership_spoofing(self):
        wrong_agent = self.runtime_event("spoof-agent", agent_id="agent-other")
        wrong_instance = self.runtime_event("spoof-instance", instance_id="missing-instance")
        result = self.repo.ingest_agent_events("agent-c1", [wrong_agent, wrong_instance])
        self.assertEqual(result["accepted"], 0)
        self.assertEqual(result["rejected"], 2)

    def test_authenticated_heartbeat_ingests_and_returns_ack(self):
        event = self.runtime_event("heartbeat-event")
        result = record_agent_heartbeat("agent-c1", {
            "agent_id": "agent-c1",
            "hostname": "agent-host",
            "runtime_events": [event],
        }, backend=self.backend)
        self.assertEqual(result["events_accepted"], 1)
        self.assertEqual(result["events_created"], 1)
        self.assertEqual(result["accepted_event_ids"], ["heartbeat-event"])
        stored = self.repo.get("heartbeat-event")
        self.assertEqual(stored["source"], "agent.runtime")

    def test_event_subject_survives_instance_deletion(self):
        self.repo.publish({
            "event_id": "deleted-subject-event",
            "event_type": "INSTANCE_REMOVED",
            "source": "controller.instance",
            "instance_id": "instance-c1",
            "data": {},
        })
        with self.backend.transaction() as connection:
            connection.execute("DELETE FROM instances WHERE id=?", ("instance-c1",))
        stored = self.repo.get("deleted-subject-event")
        self.assertEqual(stored["instance_id"], "instance-c1")


class AgentRuntimeEventQueueTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_emit_read_and_ack_is_delivery_buffer_contract(self):
        one = emit_runtime_event(
            self.state,
            "INSTANCE_DRIFT_DETECTED",
            instance_id="instance-one",
            agent_id="agent-one",
            data={"observed_state": "stopped"},
            severity="warning",
        )
        two = emit_runtime_event(
            self.state,
            "INSTANCE_RECOVERED",
            instance_id="instance-one",
            agent_id="agent-one",
        )
        queued = read_runtime_events(self.state)
        self.assertEqual([item["event_id"] for item in queued], [one["event_id"], two["event_id"]])
        removed = acknowledge_runtime_events(self.state, [one["event_id"]])
        self.assertEqual(removed, 1)
        remaining = read_runtime_events(self.state)
        self.assertEqual([item["event_id"] for item in remaining], [two["event_id"]])


if __name__ == "__main__":
    unittest.main()
