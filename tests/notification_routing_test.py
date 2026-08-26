#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "dashboard" / "workers"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from notification_dispatcher import NotificationDispatcher
from notification_outbox_repository import NotificationOutboxRepository
from notification_routing_repository import NotificationRoutingRepository


class NotificationRoutingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(self.root / "capivara.db"),
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

    def test_dispatches_discord_from_secret_file_without_persisting_webhook(self):
        secret = self.root / "discord-webhook"
        webhook = "https://discord.example.invalid/api/webhooks/sensitive-token"
        secret.write_text(webhook + "\n", encoding="utf-8")
        destination_id = self.routing.create_destination(
            name="Discord operações",
            channel="discord",
            recipient="operations",
            secret_file=str(secret),
        )
        self.routing.create_route(destination_id=destination_id, minimum_severity="critical")
        self.routing.enqueue_event(
            event_id="event-discord",
            event_type="INSTANCE_PROVISION_FAILED",
            severity="critical",
            message="Falha de provisionamento",
        )
        response = MagicMock()
        response.status = 204
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("notification_dispatcher.urllib.request.urlopen", return_value=response) as urlopen:
            delivered = NotificationDispatcher(self.backend).cycle()
        self.assertEqual(delivered, 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, webhook)
        self.assertIn("Falha de provisionamento", request.data.decode("utf-8"))
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT status,last_error FROM notification_outbox WHERE event_id=?",
                ("event-discord",),
            ).fetchone()
        self.assertEqual(row["status"], "delivered")
        self.assertIsNone(row["last_error"])
        self.assertNotIn(webhook, str(NotificationOutboxRepository(self.backend).pending()))

    def test_dispatches_email_using_nonsecret_config_and_secret_password_file(self):
        secret = self.root / "smtp-password"
        secret.write_text("super-secret-password\n", encoding="utf-8")
        destination_id = self.routing.create_destination(
            name="E-mail operações",
            channel="email",
            recipient="ops@example.invalid",
            secret_file=str(secret),
            config={
                "host": "smtp.example.invalid",
                "port": 587,
                "sender": "capivara@example.invalid",
                "username": "capivara",
                "tls": "starttls",
            },
        )
        self.routing.create_route(destination_id=destination_id, minimum_severity="warning")
        self.routing.enqueue_event(
            event_id="event-email",
            event_type="INSTANCE_DEGRADED",
            severity="warning",
            message="Instância degradada",
            subject="Capivara: instância degradada",
        )
        smtp = MagicMock()
        with patch("notification_dispatcher.smtplib.SMTP", return_value=smtp):
            delivered = NotificationDispatcher(self.backend).cycle()
        self.assertEqual(delivered, 1)
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("capivara", "super-secret-password")
        smtp.send_message.assert_called_once()
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "ops@example.invalid")
        self.assertEqual(message["From"], "capivara@example.invalid")
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT status,last_error FROM notification_outbox WHERE event_id=?",
                ("event-email",),
            ).fetchone()
        self.assertEqual(row["status"], "delivered")
        self.assertIsNone(row["last_error"])

    def test_delivery_failure_retries_then_becomes_terminal_without_secret_leak(self):
        secret = self.root / "discord-retry"
        secret.write_text("https://discord.example.invalid/api/webhooks/private-token\n", encoding="utf-8")
        destination_id = self.routing.create_destination(
            name="Discord retry",
            channel="discord",
            recipient="retry",
            secret_file=str(secret),
        )
        self.routing.create_route(destination_id=destination_id, minimum_severity="critical")
        self.routing.enqueue_event(
            event_id="event-retry",
            event_type="INFRASTRUCTURE_DEGRADED",
            severity="critical",
            message="Falha persistente",
        )
        dispatcher = NotificationDispatcher(self.backend, max_attempts=1)
        with patch("notification_dispatcher.urllib.request.urlopen", side_effect=OSError("network failed")):
            self.assertEqual(dispatcher.cycle(), 0)
        with self.backend.connect() as connection:
            row = connection.execute(
                "SELECT status,attempts,last_error FROM notification_outbox WHERE event_id=?",
                ("event-retry",),
            ).fetchone()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 1)
        self.assertNotIn("private-token", str(row["last_error"]))


if __name__ == "__main__":
    unittest.main()
