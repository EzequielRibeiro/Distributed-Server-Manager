import base64
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

if str(DATABASE_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(DATABASE_DIR),
    )


import manager as DB
import alerts as ALERTS


spec = importlib.util.spec_from_file_location(
    "capivara_dashboard_server_alert_http_test",
    ROOT / "dashboard" / "server.py",
)

SERVER = importlib.util.module_from_spec(
    spec
)

spec.loader.exec_module(
    SERVER
)


class _FakeSocket:
    def makefile(
        self,
        mode,
        buffering=None,
    ):
        if "r" in mode:
            return io.BytesIO()

        return io.BytesIO()


class DashboardAlertHTTPTest(
    unittest.TestCase
):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()

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
                        'controller-a',
                        'Controller A',
                        'controller'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO nodes(
                        id,
                        name,
                        role
                    )
                    VALUES (
                        'controller-b',
                        'Controller B',
                        'controller'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO nodes(
                        id,
                        name,
                        role
                    )
                    VALUES (
                        'agent-a',
                        'Agent A',
                        'agent'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO nodes(
                        id,
                        name,
                        role
                    )
                    VALUES (
                        'agent-b',
                        'Agent B',
                        'agent'
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
                        'controller-a',
                        'controller-a',
                        'Controller A'
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
                        'controller-b',
                        'controller-b',
                        'Controller B'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO agents(
                        id,
                        controller_id,
                        node_id,
                        name
                    )
                    VALUES (
                        'agent-a',
                        'controller-a',
                        'agent-a',
                        'Agent A'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO agents(
                        id,
                        controller_id,
                        node_id,
                        name
                    )
                    VALUES (
                        'agent-b',
                        'controller-b',
                        'agent-b',
                        'Agent B'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO customers(
                        id,
                        controller_id,
                        name
                    )
                    VALUES (
                        'customer-a',
                        'controller-a',
                        'Customer A'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO customers(
                        id,
                        controller_id,
                        name
                    )
                    VALUES (
                        'customer-b',
                        'controller-b',
                        'Customer B'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO instances(
                        id,
                        node_id,
                        game_id,
                        name,
                        controller_id,
                        agent_id,
                        customer_id
                    )
                    VALUES (
                        'instance-a',
                        'agent-a',
                        'minecraft',
                        'Instance A',
                        'controller-a',
                        'agent-a',
                        'customer-a'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO instances(
                        id,
                        node_id,
                        game_id,
                        name,
                        controller_id,
                        agent_id,
                        customer_id
                    )
                    VALUES (
                        'instance-b',
                        'agent-b',
                        'minecraft',
                        'Instance B',
                        'controller-b',
                        'agent-b',
                        'customer-b'
                    )
                    """
                )

        self._create_user(
            "admin-test",
            "Password123!",
            "admin",
            None,
        )

        self._create_user(
            "controller-a-user",
            "Password123!",
            "controller",
            "controller-a",
        )

        self._create_user(
            "customer-a-user",
            "Password123!",
            "customer",
            "customer-a",
        )

        self._create_user(
            "customer-b-user",
            "Password123!",
            "customer",
            "customer-b",
        )

        self._open_instance_alert(
            "alert-instance-a",
            "controller-a",
            "agent-a",
            "instance-a",
        )

        self._open_instance_alert(
            "alert-instance-b",
            "controller-b",
            "agent-b",
            "instance-b",
        )

        self.original_database_file = (
            SERVER.DATABASE_FILE
        )

        self.original_load_users = (
            SERVER.load_users
        )

        SERVER.DATABASE_FILE = (
            self.database
        )

        SERVER.load_users = (
            lambda database_path=self.database:
            self.original_load_users(
                database_path
            )
        )

    def tearDown(self):
        SERVER.load_users = (
            self.original_load_users
        )

        SERVER.DATABASE_FILE = (
            self.original_database_file
        )

        self.temporary.cleanup()

    def _create_user(
        self,
        username,
        password,
        role,
        scope_id,
    ):
        with closing(
            DB.connect(
                self.database
            )
        ) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO dashboard_users(
                        username,
                        password_hash,
                        role,
                        scope_id,
                        active
                    )
                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        1
                    )
                    """,
                    (
                        username,
                        SERVER.hash_password(
                            password
                        ),
                        role,
                        scope_id,
                    ),
                )

    def _open_instance_alert(
        self,
        alert_id,
        controller_id,
        agent_id,
        instance_id,
    ):
        ALERTS.open_alert(
            self.database,
            alert_id=alert_id,
            rule_id=f"rule.{alert_id}",
            level="WARNING",
            message=f"Mensagem {alert_id}",
            scope="instance",
            controller_id=controller_id,
            agent_id=agent_id,
            node_id=agent_id,
            instance_id=instance_id,
        )

    def _authorization(
        self,
        username,
        password="Password123!",
    ):
        raw = (
            f"{username}:{password}"
            .encode("utf-8")
        )

        token = base64.b64encode(
            raw
        ).decode("ascii")

        return f"Basic {token}"

    def _request(
        self,
        *,
        path,
        username,
    ):
        handler = SERVER.DashboardHandler.__new__(
            SERVER.DashboardHandler
        )

        handler.command = "POST"
        handler.path = path
        handler.request_version = "HTTP/1.1"
        handler.close_connection = True

        handler.headers = {
            "Authorization": self._authorization(
                username
            ),
        }

        response = {
            "code": None,
            "payload": None,
            "forbidden": False,
        }

        def send_json(
            code,
            payload,
        ):
            response["code"] = code
            response["payload"] = payload

        def forbidden():
            response["code"] = 403
            response["forbidden"] = True

        def unauthorized():
            response["code"] = 401

        handler.send_json = send_json
        handler.forbidden = forbidden
        handler.unauthorized = unauthorized

        SERVER.DashboardHandler.do_POST(
            handler
        )

        return response

    def test_customer_can_ack_own_alert_over_http(self):
        response = self._request(
            path=(
                "/api/acknowledge"
                "?id=alert-instance-a"
            ),
            username="customer-a-user",
        )

        self.assertEqual(
            response["code"],
            200,
            response,
        )

        self.assertTrue(
            response["payload"]["ok"]
        )

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-a",
        )

        self.assertEqual(
            alert["state"],
            "ACKNOWLEDGED",
        )

    def test_customer_cannot_ack_other_customer_alert(self):
        response = self._request(
            path=(
                "/api/acknowledge"
                "?id=alert-instance-b"
            ),
            username="customer-a-user",
        )

        self.assertEqual(
            response["code"],
            403,
            response,
        )

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-b",
        )

        self.assertEqual(
            alert["state"],
            "OPEN",
        )

    def test_controller_cannot_ack_other_controller_alert(self):
        response = self._request(
            path=(
                "/api/acknowledge"
                "?id=alert-instance-b"
            ),
            username="controller-a-user",
        )

        self.assertEqual(
            response["code"],
            403,
            response,
        )

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-b",
        )

        self.assertEqual(
            alert["state"],
            "OPEN",
        )

    def test_admin_can_ack_any_alert(self):
        response = self._request(
            path=(
                "/api/acknowledge"
                "?id=alert-instance-b"
            ),
            username="admin-test",
        )

        self.assertEqual(
            response["code"],
            200,
            response,
        )

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-b",
        )

        self.assertEqual(
            alert["state"],
            "ACKNOWLEDGED",
        )

    def test_missing_alert_returns_422(self):
        response = self._request(
            path=(
                "/api/acknowledge"
                "?id=does-not-exist"
            ),
            username="admin-test",
        )

        self.assertEqual(
            response["code"],
            422,
            response,
        )

        self.assertFalse(
            response["payload"]["ok"]
        )

        self.assertEqual(
            response["payload"]["error"],
            "alert not found",
        )

    def test_missing_id_returns_400(self):
        response = self._request(
            path="/api/acknowledge",
            username="admin-test",
        )

        self.assertEqual(
            response["code"],
            400,
            response,
        )

        self.assertFalse(
            response["payload"]["ok"]
        )

    def test_acknowledged_alert_cannot_be_acknowledged_again(self):
        ALERTS.acknowledge_alert(
            self.database,
            "alert-instance-a",
        )

        response = self._request(
            path=(
                "/api/acknowledge"
                "?id=alert-instance-a"
            ),
            username="admin-test",
        )

        self.assertEqual(
            response["code"],
            422,
            response,
        )

        self.assertIn(
            "only OPEN alerts",
            response["payload"]["error"],
        )

    def test_resolved_alert_cannot_be_acknowledged(self):
        ALERTS.resolve_alert(
            self.database,
            "alert-instance-a",
        )

        response = self._request(
            path=(
                "/api/acknowledge"
                "?id=alert-instance-a"
            ),
            username="admin-test",
        )

        self.assertEqual(
            response["code"],
            422,
            response,
        )

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-a",
        )

        self.assertEqual(
            alert["state"],
            "RESOLVED",
        )


if __name__ == "__main__":
    unittest.main()