import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

CLI = (
    ROOT
    / "database"
    / "alert_cli.py"
)


class AlertCLITest(
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

        from contextlib import closing

        database_dir = (
            ROOT
            / "database"
        )

        if str(database_dir) not in sys.path:
            sys.path.insert(
                0,
                str(database_dir),
            )

        import manager as DB

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
                        'controller-test',
                        'Controller Test',
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
                        'controller-test',
                        'controller-test',
                        'Controller Test'
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
        *,
        level="WARNING",
        alert_id="cli-test",
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
            "Mensagem CLI",
            "--scope",
            "controller",
            "--controller-id",
            "controller-test",
        )

    def test_open_alert(self):
        result, payload = (
            self.open_alert()
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["id"],
            "cli-test",
        )

        self.assertEqual(
            payload["level"],
            "WARNING",
        )

    def test_lowercase_warning_is_normalized(self):
        result, payload = (
            self.open_alert(
                level="warning",
            )
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["level"],
            "WARNING",
        )

    def test_success_maps_to_info(self):
        result, payload = (
            self.open_alert(
                level="success",
            )
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

    def test_ok_maps_to_info(self):
        result, payload = (
            self.open_alert(
                level="OK",
            )
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

    def test_invalid_level_is_rejected(self):
        result, payload = (
            self.open_alert(
                level="UNKNOWN",
            )
        )

        self.assertEqual(
            result.returncode,
            2,
        )

        self.assertFalse(
            payload["ok"]
        )

    def test_active_lists_open_alert(self):
        self.open_alert()

        result, payload = self.run_cli(
            "active"
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
            payload[0]["id"],
            "cli-test",
        )

    def test_count_counts_active_alert(self):
        self.open_alert()

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

    def test_acknowledge_alert(self):
        self.open_alert()

        result, payload = self.run_cli(
            "ack",
            "cli-test",
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

    def test_resolve_alert(self):
        self.open_alert()

        result, payload = self.run_cli(
            "resolve",
            "cli-test",
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

    def test_resolved_alert_not_in_active(self):
        self.open_alert()

        self.run_cli(
            "resolve",
            "cli-test",
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

    def test_history_preserves_resolved_alert(self):
        self.open_alert()

        self.run_cli(
            "resolve",
            "cli-test",
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

    def test_event_history_contains_open_and_resolve(self):
        self.open_alert()

        self.run_cli(
            "resolve",
            "cli-test",
        )

        result, payload = self.run_cli(
            "history",
            "cli-test",
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
                "RESOLVE",
            ],
        )


if __name__ == "__main__":
    unittest.main()