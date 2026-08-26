#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database",):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from notification_outbox_repository import NotificationOutboxRepository
from notification_routing_repository import NotificationRoutingRepository


class NotificationRoutingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.temp.name) / "capivara.db"),
        ))
        self.backend.initialize()
        self.routing = NotificationRoutingRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_routes_events_to_configured_database_destinations(self):
        email = self.routing.create_destination(
            name="Operações por e-mail",
            channel="email",
            recipient="ops@example.invalid",
            config={"sender": "capivara@example.invalid"},
        )
        discord = self.routing.create_destination(
            name="Discord NOC",
            channel="discord",
            recipient="noc",
            secret_file="/run/secrets/capivara-discord-noc",
        )
        self.routing.create_route(destination_id=email, minimum_severity="warning")
        self.routing.create_route(
            destination_id=discord,
            event_type="INSTANCE_PROVISION_FAILED",
            minimum_severity="critical",
        )

        self.assertEqual(
            self.routing.matching_destinations(event_type="INSTANCE_STARTED", severity="info"),
            [],
        )
        warning = self.routing.matching_destinations(event_type="INSTANCE_DEGRADED", severity="warning")
        self.assertEqual([row["destination_id"] for row in warning], [email])

        ids = self.routing.enqueue_event(
            event_id="event-1",
            event_type="INSTANCE_PROVISION_FAILED",
            severity="critical",
            message="Falha ao provisionar a instância",
            subject="Falha de provisionamento",
            alert_id="alert-1",
        )
        self.assertEqual(len(ids), 2)
        rows = NotificationOutboxRepository(self.backend).pending()
        self.assertEqual({row["channel"] for row in rows}, {"email", "discord"})
        self.assertEqual({row["recipient"] for row in rows}, {"ops@example.invalid", "noc"})
        self.assertTrue(all(row["event_id"] == "event-1" for row in rows))
        self.assertTrue(all(row["alert_id"] == "alert-1" for row in rows))

    def test_disabled_destination_is_not_routed(self):
        destination_id = self.routing.create_destination(
            name="Destino temporário",
            channel="email",
            recipient="disabled@example.invalid",
        )
        self.routing.create_route(destination_id=destination_id, minimum_severity="info")
        self.routing.set_destination_enabled(destination_id, False)
        self.assertEqual(
            self.routing.enqueue_event(
                event_id="event-2",
                event_type="INSTANCE_STARTED",
                severity="info",
                message="Instância iniciada",
            ),
            [],
        )

    def test_secret_values_are_referenced_not_stored_in_outbox(self):
        destination_id = self.routing.create_destination(
            name="Webhook seguro",
            channel="discord",
            recipient="noc-secure",
            secret_file="/run/secrets/discord-webhook",
        )
        self.routing.create_route(destination_id=destination_id, minimum_severity="critical")
        self.routing.enqueue_event(
            event_id="event-3",
            event_type="INFRASTRUCTURE_DEGRADED",
            severity="critical",
            message="Infraestrutura degradada",
        )
        outbox = NotificationOutboxRepository(self.backend).pending()
        serialized = str(outbox)
        self.assertNotIn("/run/secrets/discord-webhook", serialized)
        destinations = self.routing.list_destinations()
        self.assertEqual(destinations[0]["secret_file"], "/run/secrets/discord-webhook")


if __name__ == "__main__":
    unittest.main()
