#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "database") not in sys.path:
    sys.path.insert(0, str(ROOT / "database"))

from backend import DatabaseConfig
from backend_factory import create_backend
from notification_routing_repository import NotificationRoutingRepository


class NotificationConfigurationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(DatabaseConfig(
            driver="sqlite",
            database=str(Path(self.temp.name) / "capivara.db"),
        ))
        self.backend.initialize()
        self.repo = NotificationRoutingRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_only_dispatcher_supported_channels_can_be_configured(self):
        with self.assertRaisesRegex(ValueError, "email or discord"):
            self.repo.create_destination(
                name="Canal desconhecido",
                channel="filesystem",
                recipient="queue.json",
            )

    def test_secret_values_are_rejected_from_database_config(self):
        with self.assertRaisesRegex(ValueError, "secret_file"):
            self.repo.create_destination(
                name="Discord inseguro",
                channel="discord",
                recipient="noc",
                config={"webhook_url": "https://example.invalid/private-token"},
            )
        with self.assertRaisesRegex(ValueError, "secret_file"):
            self.repo.create_destination(
                name="SMTP inseguro",
                channel="email",
                recipient="ops@example.invalid",
                config={"password": "do-not-store"},
            )

    def test_routing_supports_every_canonical_universal_event_severity(self):
        destination_id = self.repo.create_destination(
            name="Todos os eventos",
            channel="email",
            recipient="events@example.invalid",
        )
        self.repo.create_route(destination_id=destination_id, minimum_severity="debug")
        for severity in ("debug", "info", "warning", "error", "critical"):
            matches = self.repo.matching_destinations(event_type="TEST_EVENT", severity=severity)
            self.assertEqual([row["destination_id"] for row in matches], [destination_id])

    def test_destination_channel_is_immutable_during_update(self):
        destination_id = self.repo.create_destination(
            name="NOC",
            channel="discord",
            recipient="noc",
            secret_file="/run/secrets/noc-webhook",
        )
        updated = self.repo.update_destination(
            destination_id,
            name="NOC principal",
            recipient="noc-primary",
            secret_file="/run/secrets/noc-webhook-v2",
            enabled=False,
        )
        self.assertEqual(updated["channel"], "discord")
        self.assertEqual(updated["name"], "NOC principal")
        self.assertEqual(updated["recipient"], "noc-primary")
        self.assertFalse(updated["enabled"])


if __name__ == "__main__":
    unittest.main()
