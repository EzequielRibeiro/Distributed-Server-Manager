from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from event_repository import EventRepository
from core.events.alerts import AlertConsumer, AlertSeverity
from core.events.automation import AutomationEngine, AutomationRule
from core.events.models import EventSeverity, EventSource, UniversalEvent
from core.events.observability import EventPlatformMetrics, ObservedEventSink
from core.events.retention import EventRetentionPolicy, EventRetentionService
from core.events.runtime import EventPlatformRuntime
from core.events.streaming import CompositeEventSink, EventStreamHub


class UniversalEventConsumerTest(unittest.TestCase):
    @staticmethod
    def event(event_type: str, *, severity: EventSeverity = EventSeverity.INFO) -> UniversalEvent:
        return UniversalEvent(
            type=event_type,
            source=EventSource(type="agent", id="agent-a"),
            severity=severity,
        )

    def test_alert_severity_is_policy_not_event_severity(self):
        event = self.event("AGENT_UPDATE_FAILED", severity=EventSeverity.CRITICAL)

        candidates = AlertConsumer().consume(event)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].level, AlertSeverity.WARNING)
        self.assertEqual(candidates[0].event_id, event.id)

    def test_non_alerting_event_produces_no_candidate(self):
        self.assertEqual(AlertConsumer().consume(self.event("AGENT_ONLINE")), [])

    def test_alert_consumer_can_forward_policy_candidates(self):
        forwarded = []
        consumer = AlertConsumer(candidate_sink=forwarded.append)
        event = self.event("AGENT_UPDATE_FAILED")

        consumer(event)

        self.assertEqual(len(forwarded), 1)
        self.assertEqual(forwarded[0].event_id, event.id)

    def test_stream_hub_fans_out_and_unsubscribes(self):
        hub = EventStreamHub()
        received_a = []
        received_b = []
        subscription = hub.subscribe(received_a.append)
        hub.subscribe(received_b.append)
        event = self.event("AGENT_ONLINE")

        hub.publish(event)
        self.assertEqual(received_a, [event])
        self.assertEqual(received_b, [event])
        self.assertEqual(hub.subscriber_count, 2)

        self.assertTrue(hub.unsubscribe(subscription))
        hub.publish(event)
        self.assertEqual(received_a, [event])
        self.assertEqual(received_b, [event, event])

    def test_composite_sink_preserves_consumer_order(self):
        calls = []
        sink = CompositeEventSink((
            lambda event: calls.append(("first", event.id)),
            lambda event: calls.append(("second", event.id)),
        ))
        event = self.event("AGENT_ONLINE")

        sink(event)

        self.assertEqual([name for name, _ in calls], ["first", "second"])

    def test_automation_executes_only_explicit_registered_rule(self):
        handled = []
        engine = AutomationEngine((
            AutomationRule.for_event_type(
                "block-placement-on-agent-offline",
                "AGENT_OFFLINE",
                handled.append,
            ),
        ))

        online = engine.handle(self.event("AGENT_ONLINE"))
        offline_event = self.event("AGENT_OFFLINE")
        offline = engine.handle(offline_event)

        self.assertEqual(online, ())
        self.assertEqual(offline, ("block-placement-on-agent-offline",))
        self.assertEqual(handled, [offline_event])

    def test_automation_rejects_duplicate_rule_ids(self):
        engine = AutomationEngine()
        rule = AutomationRule.for_event_type("same", "AGENT_OFFLINE", lambda event: None)
        engine.register(rule)
        with self.assertRaises(ValueError):
            engine.register(rule)

    def test_observability_records_success_and_failure(self):
        metrics = EventPlatformMetrics()
        stored = []
        observed = ObservedEventSink(stored.append, metrics)
        event = self.event("AGENT_ONLINE")

        observed(event)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot.published_total, 1)
        self.assertEqual(snapshot.failed_total, 0)
        self.assertEqual(snapshot.by_type["AGENT_ONLINE"], 1)
        self.assertEqual(snapshot.last_event_id, event.id)
        self.assertTrue(snapshot.healthy)

        def fail(_event):
            raise RuntimeError("sink failed")

        with self.assertRaises(RuntimeError):
            ObservedEventSink(fail, metrics)(event)
        self.assertEqual(metrics.snapshot().failed_total, 1)
        self.assertFalse(metrics.snapshot().healthy)

    def test_runtime_composes_store_stream_alerts_automation_and_metrics(self):
        stored = []
        streamed = []
        candidates = []
        automated = []
        stream = EventStreamHub()
        stream.subscribe(streamed.append)
        alerts = AlertConsumer(candidate_sink=candidates.append)
        automation = AutomationEngine((
            AutomationRule.for_event_type(
                "record-update-failure",
                "AGENT_UPDATE_FAILED",
                automated.append,
            ),
        ))
        runtime = EventPlatformRuntime(
            stored.append,
            stream=stream,
            alerts=alerts,
            automation=automation,
        )

        event = runtime.publisher.publish(
            "AGENT_UPDATE_FAILED",
            source=EventSource(type="agent", id="agent-a"),
            severity=EventSeverity.CRITICAL,
        )

        self.assertEqual(stored, [event])
        self.assertEqual(streamed, [event])
        self.assertEqual(candidates[0].level, AlertSeverity.WARNING)
        self.assertEqual(automated, [event])
        self.assertEqual(runtime.snapshot().published_total, 1)


class UniversalEventRetentionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "events.db"))
        )
        self.backend.initialize()
        self.repository = EventRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_retention_dry_run_then_deletes_only_old_universal_events(self):
        now = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)
        old = UniversalEvent(
            type="AGENT_ONLINE",
            source=EventSource(type="agent", id="agent-old"),
            timestamp=now - timedelta(days=120),
        )
        recent = UniversalEvent(
            type="AGENT_ONLINE",
            source=EventSource(type="agent", id="agent-new"),
            timestamp=now - timedelta(days=2),
        )
        self.repository.store(old)
        self.repository.store(recent)
        service = EventRetentionService(
            self.repository,
            EventRetentionPolicy(max_age_days=90),
        )

        preview = service.run(now=now, dry_run=True)
        self.assertEqual(preview.matched, 1)
        self.assertEqual(preview.deleted, 0)
        self.assertIsNotNone(self.repository.get(old.id))

        applied = service.run(now=now, dry_run=False)
        self.assertEqual(applied.matched, 1)
        self.assertEqual(applied.deleted, 1)
        self.assertIsNone(self.repository.get(old.id))
        self.assertIsNotNone(self.repository.get(recent.id))


if __name__ == "__main__":
    unittest.main()
