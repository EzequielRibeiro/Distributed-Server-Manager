import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from event_repository import EventRepository
from core.events import EventPublisher, EventScope, EventSeverity, EventSource
from core.events.timeline import TimelineConsumer


class UniversalEventTimelineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        self.repository = EventRepository(self.backend)
        self.publisher = EventPublisher(sink=self.repository.store)
        self.timeline = TimelineConsumer(self.repository)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_timeline_reads_universal_events_by_agent_scope(self):
        self.publisher.publish(
            "AGENT_ONLINE",
            source=EventSource(type="agent", id="agent-a"),
            scope=EventScope(agent_id="agent-a"),
            data={"previous_status": "pairing", "status": "active"},
            correlation_id="corr-agent-a",
        )
        self.publisher.publish(
            "AGENT_DISABLED",
            source=EventSource(type="agent", id="agent-b"),
            scope=EventScope(agent_id="agent-b"),
            severity=EventSeverity.WARNING,
            data={"previous_status": "active", "status": "disabled"},
        )

        entries = self.timeline.entries(agent_id="agent-a")

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].type, "AGENT_ONLINE")
        self.assertEqual(entries[0].scope["agent_id"], "agent-a")
        self.assertEqual(entries[0].correlation_id, "corr-agent-a")

    def test_timeline_can_follow_one_correlation_chain_in_order(self):
        first = self.publisher.publish(
            "AGENT_UPDATE_STARTED",
            source=EventSource(type="agent", id="agent-a"),
            scope=EventScope(agent_id="agent-a"),
            correlation_id="corr-rollout-1",
            data={"desired_version": "2.0.0"},
        )
        self.publisher.publish(
            "AGENT_UPDATE_COMPLETED",
            source=EventSource(type="agent", id="agent-a"),
            scope=EventScope(agent_id="agent-a"),
            correlation_id="corr-rollout-1",
            causation_id=first.id,
            data={"installed_version": "2.0.0"},
        )

        entries = self.timeline.entries(
            correlation_id="corr-rollout-1",
            newest_first=False,
        )

        self.assertEqual([entry.type for entry in entries], [
            "AGENT_UPDATE_STARTED",
            "AGENT_UPDATE_COMPLETED",
        ])
        self.assertEqual(entries[1].causation_id, entries[0].id)

    def test_timeline_entry_is_ui_ready_without_synthetic_text(self):
        self.publisher.publish(
            "AGENT_OFFLINE",
            source=EventSource(type="agent", id="agent-a"),
            scope=EventScope(agent_id="agent-a"),
            severity=EventSeverity.WARNING,
            data={"reason": "administrative_transition"},
        )

        payload = self.timeline.entries(agent_id="agent-a")[0].to_dict()

        self.assertEqual(payload["type"], "AGENT_OFFLINE")
        self.assertEqual(payload["severity"], "warning")
        self.assertEqual(payload["source"], {"type": "agent", "id": "agent-a"})
        self.assertEqual(payload["data"]["reason"], "administrative_transition")
        self.assertTrue(payload["timestamp"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
