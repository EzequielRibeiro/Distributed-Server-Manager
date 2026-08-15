import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"
CLI = DATABASE_DIR / "alert_cli.py"

if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(DATABASE_DIR),
    )


import manager as DB


class AlertCLIE2ETest(
    unittest.TestCase
):
    def setUp(self):
        self.temporary = (
            tempfile.TemporaryDirectory()
        )

        self.root = Path(
            self.temporary.name
        )

        self.database = (
            self.root
            / "data"
            / "capivara.db"
        )

        DB.initialize(
            self.database
        )

        with closing(
            DB.connect(
                self.database
            )
        ) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO nodes(
                        id,
                        name,
                        role
                    )
                    VALUES (
                        'controller-e2e',
                        'Controller E2E',
                        'controller'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO controllers(
                        id,
                        node_id,
                        name
                    )
                    VALUES (
                        'controller-e2e',
                        'controller-e2e',
                        'Controller E2E'
                    )
                    """
                )

        self.environment = (
            os.environ.copy()
        )

        self.environment[
            "DSM_ROOT"
        ] = str(
            self.root
        )

        self.environment[
            "DSM_DATABASE"
        ] = str(
            self.database
        )

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(
        self,
        *arguments,
    ):
        result = subprocess.run(
            [
                sys.executable,
                str(CLI),
                *arguments,
            ],
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )

        payload = None

        if result.stdout.strip():
            payload = json.loads(
                result.stdout
            )

        return (
            result,
            payload,
        )

    def open_alert(
        self,
        alert_id="e2e-alert",
        level="WARNING",
        controller_id="controller-e2e",
    ):
        return self.run_cli(
            "open",
            "--id",
            alert_id,
            "--rule-id",
            f"rule.{alert_id}",
            "--level",
            level,
            "--message",
            "Mensagem E2E",
            "--scope",
            "controller",
            "--controller-id",
            controller_id,
        )

    def database_alert(
        self,
        alert_id,
    ):
        connection = sqlite3.connect(
            self.database
        )

        connection.row_factory = (
            sqlite3.Row
        )

        try:
            row = connection.execute(
                """
                SELECT *
                FROM alerts
                WHERE id=?
                """,
                (
                    alert_id,
                ),
            ).fetchone()

            if row is None:
                return None

            return dict(
                row
            )

        finally:
            connection.close()

    def database_events(
        self,
        alert_id,
    ):
        connection = sqlite3.connect(
            self.database
        )

        connection.row_factory = (
            sqlite3.Row
        )

        try:
            rows = connection.execute(
                """
                SELECT *
                FROM alert_events
                WHERE alert_id=?
                ORDER BY id
                """,
                (
                    alert_id,
                ),
            ).fetchall()

            return [
                dict(row)
                for row in rows
            ]

        finally:
            connection.close()

    def test_complete_alert_lifecycle(self):
        result, payload = (
            self.open_alert()
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["state"],
            "OPEN",
        )

        stored = self.database_alert(
            "e2e-alert"
        )

        self.assertIsNotNone(
            stored
        )

        self.assertEqual(
            stored["controller_id"],
            "controller-e2e",
        )

        self.assertEqual(
            stored["state"],
            "OPEN",
        )

        result, payload = self.run_cli(
            "active"
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            {
                item["id"]
                for item in payload
            },
            {
                "e2e-alert",
            },
        )

        result, payload = self.run_cli(
            "count"
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["count"],
            1,
        )

        result, payload = self.run_cli(
            "ack",
            "e2e-alert",
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["state"],
            "ACKNOWLEDGED",
        )

        stored = self.database_alert(
            "e2e-alert"
        )

        self.assertEqual(
            stored["state"],
            "ACKNOWLEDGED",
        )

        result, payload = self.run_cli(
            "resolve",
            "e2e-alert",
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["state"],
            "RESOLVED",
        )

        stored = self.database_alert(
            "e2e-alert"
        )

        self.assertEqual(
            stored["state"],
            "RESOLVED",
        )

        result, payload = self.run_cli(
            "active"
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload,
            [],
        )

        result, payload = self.run_cli(
            "count"
        )

        self.assertEqual(
            payload["count"],
            0,
        )

        result, payload = self.run_cli(
            "history"
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            len(payload),
            1,
        )

        self.assertEqual(
            payload[0]["state"],
            "RESOLVED",
        )

        result, payload = self.run_cli(
            "history",
            "e2e-alert",
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            [
                event["action"]
                for event in payload
            ],
            [
                "OPEN",
                "ACK",
                "RESOLVE",
            ],
        )

        events = self.database_events(
            "e2e-alert"
        )

        self.assertEqual(
            [
                event["action"]
                for event in events
            ],
            [
                "OPEN",
                "ACK",
                "RESOLVE",
            ],
        )

    def test_success_is_persisted_as_info(self):
        result, payload = self.open_alert(
            alert_id="e2e-success",
            level="SUCCESS",
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["level"],
            "INFO",
        )

        stored = self.database_alert(
            "e2e-success"
        )

        self.assertEqual(
            stored["level"],
            "INFO",
        )

    def test_ok_is_persisted_as_info(self):
        result, payload = self.open_alert(
            alert_id="e2e-ok",
            level="OK",
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["level"],
            "INFO",
        )

        stored = self.database_alert(
            "e2e-ok"
        )

        self.assertEqual(
            stored["level"],
            "INFO",
        )

    def test_invalid_controller_is_rejected_by_integrity(self):
        result, payload = self.open_alert(
            alert_id="e2e-invalid-controller",
            controller_id="controller-does-not-exist",
        )

        self.assertNotEqual(
            result.returncode,
            0,
        )

        self.assertIsInstance(
            payload,
            dict,
        )

        self.assertFalse(
            payload["ok"]
        )

        self.assertIn(
            "FOREIGN KEY",
            payload["error"].upper(),
        )

        stored = self.database_alert(
            "e2e-invalid-controller"
        )

        self.assertIsNone(
            stored
        )

    def test_invalid_level_does_not_create_alert(self):
        result, payload = self.open_alert(
            alert_id="e2e-invalid-level",
            level="BANANA",
        )

        self.assertNotEqual(
            result.returncode,
            0,
        )

        self.assertFalse(
            payload["ok"]
        )

        self.assertIsNone(
            self.database_alert(
                "e2e-invalid-level"
            )
        )


if __name__ == "__main__":
    unittest.main()