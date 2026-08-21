import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from core.events import EventPublisher, EventScope, EventSource
from event_repository import EventRepository
from timeline_http import TIMELINE_PATH, dispatch_timeline_get


class UniversalEventTimelineHttpTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        publisher = EventPublisher(sink=EventRepository(self.backend).store)
        publisher.publish(
            "AGENT_ONLINE",
            source=EventSource(type="agent", id="agent-a"),
            scope=EventScope(controller_id="controller-a", agent_id="agent-a"),
            data={"status": "active"},
            correlation_id="corr-a",
        )
        publisher.publish(
            "AGENT_OFFLINE",
            source=EventSource(type="agent", id="agent-b"),
            scope=EventScope(controller_id="controller-b", agent_id="agent-b"),
            data={"status": "offline"},
            correlation_id="corr-b",
        )
        publisher.publish(
            "INSTANCE_CREATED",
            source=EventSource(type="controller", id="controller-a"),
            scope=EventScope(controller_id="controller-a", customer_id="customer-a"),
            data={"instance": "demo"},
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_controller_is_forced_to_own_scope(self):
        status, body = dispatch_timeline_get(
            TIMELINE_PATH,
            "",
            user={"role": "controller", "scope_id": "controller-a"},
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["items"])
        self.assertTrue(
            all(item["scope"].get("controller_id") == "controller-a" for item in body["items"])
        )

    def test_controller_cannot_request_other_controller(self):
        status, body = dispatch_timeline_get(
            TIMELINE_PATH,
            "controller_id=controller-b",
            user={"role": "controller", "scope_id": "controller-a"},
            backend=self.backend,
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden")

    def test_customer_is_forced_to_own_scope(self):
        status, body = dispatch_timeline_get(
            TIMELINE_PATH,
            "",
            user={"role": "customer", "scope_id": "customer-a"},
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["scope"]["customer_id"], "customer-a")

    def test_admin_can_filter_and_choose_ascending_order(self):
        status, body = dispatch_timeline_get(
            TIMELINE_PATH,
            "controller_id=controller-a&order=asc&limit=10",
            user={"role": "admin"},
            backend=self.backend,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["order"], "asc")
        self.assertEqual(body["count"], 2)

    def test_unknown_event_type_and_invalid_limit_are_rejected(self):
        status, body = dispatch_timeline_get(
            TIMELINE_PATH,
            "event_type=NOT_A_REAL_EVENT",
            user={"role": "admin"},
            backend=self.backend,
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_request")

        status, body = dispatch_timeline_get(
            TIMELINE_PATH,
            "limit=999",
            user={"role": "admin"},
            backend=self.backend,
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_request")

    def test_unrelated_path_is_not_claimed(self):
        self.assertIsNone(
            dispatch_timeline_get(
                "/api/other",
                "",
                user={"role": "admin"},
                backend=self.backend,
            )
        )


if __name__ == "__main__":
    unittest.main()
