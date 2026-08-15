import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

ADAPTER = (
    DATABASE_DIR
    / "alert_store.sh"
)

if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(DATABASE_DIR),
    )


import manager as DB


class AlertStoreShellAdapterTest(
    unittest.TestCase
):
    def setUp(self):
        self.bash = shutil.which(
            "bash"
        )

        if self.bash is None:
            self.skipTest(
                "bash is not available "
                "in this environment"
            )

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
                        'controller-shell',
                        'Controller Shell',
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
                        'controller-shell',
                        'controller-shell',
                        'Controller Shell'
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

        self.environment[
            "PYTHON_BIN"
        ] = sys.executable

    def tearDown(self):
        self.temporary.cleanup()

    def run_adapter(
        self,
        *arguments,
    ):
        result = subprocess.run(
            [
                self.bash,
                str(ADAPTER),
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
        alert_id="shell-alert",
        level="WARNING",
    ):
        return self.run_adapter(
            "open",
            alert_id,
            level,
            "Titulo Shell",
            "Mensagem Shell",
            "controller-shell",
            f"rule.{alert_id}",
        )

    def test_open_through_shell_adapter(self):
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
            "shell-alert",
        )

        self.assertEqual(
            payload["state"],
            "OPEN",
        )

    def test_push_alias_works(self):
        result, payload = self.run_adapter(
            "push",
            "shell-push",
            "WARNING",
            "Titulo",
            "Mensagem",
            "controller-shell",
            "rule.shell-push",
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["id"],
            "shell-push",
        )

    def test_success_maps_to_info(self):
        result, payload = (
            self.open_alert(
                alert_id="shell-success",
                level="SUCCESS",
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

    def test_warn_maps_to_warning(self):
        result, payload = (
            self.open_alert(
                alert_id="shell-warn",
                level="WARN",
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

    def test_error_maps_to_critical(self):
        result, payload = (
            self.open_alert(
                alert_id="shell-error",
                level="ERROR",
            )
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            payload["level"],
            "CRITICAL",
        )

    def test_active_and_count(self):
        self.open_alert()

        result, payload = self.run_adapter(
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

        result, payload = self.run_adapter(
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

    def test_ack_and_resolve(self):
        self.open_alert()

        result, payload = self.run_adapter(
            "ack",
            "shell-alert",
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

        result, payload = self.run_adapter(
            "resolve",
            "shell-alert",
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

    def test_history_preserves_audit(self):
        self.open_alert()

        self.run_adapter(
            "ack",
            "shell-alert",
        )

        self.run_adapter(
            "resolve",
            "shell-alert",
        )

        result, payload = self.run_adapter(
            "history",
            "shell-alert",
        )

        self.assertEqual(
            result.returncode,
            0,
            result.stderr,
        )

        self.assertEqual(
            [
                item["action"]
                for item in payload
            ],
            [
                "OPEN",
                "ACK",
                "RESOLVE",
            ],
        )

    def test_invalid_controller_is_rejected(self):
        result, payload = self.run_adapter(
            "open",
            "invalid-controller",
            "WARNING",
            "Titulo",
            "Mensagem",
            "controller-does-not-exist",
            "rule.invalid-controller",
        )

        self.assertNotEqual(
            result.returncode,
            0,
        )

        self.assertFalse(
            payload["ok"]
        )

    def test_missing_id_is_rejected(self):
        result, payload = self.run_adapter(
            "ack"
        )

        self.assertEqual(
            result.returncode,
            2,
        )

        self.assertFalse(
            payload["ok"]
        )


if __name__ == "__main__":
    unittest.main()