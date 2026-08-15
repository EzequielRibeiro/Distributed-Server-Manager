import base64
import importlib.util
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
    "capivara_dashboard_history_clear_http_test",
    ROOT / "dashboard" / "server.py",
)

SERVER = importlib.util.module_from_spec(
    spec
)

spec.loader.exec_module(
    SERVER
)


class DashboardNotificationHistoryClearHTTPTest(
    unittest.TestCase
):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()

        self.database = (
            Path(self.temporary.name)
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
                    INSERT INTO nodes(id, name, role)
                    VALUES (
                        'controller-a',
                        'Controller A',
                        'controller'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
                    VALUES (
                        'controller-b',
                        'Controller B',
                        'controller'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
                    VALUES (
                        'agent-a',
                        'Agent A',
                        'agent'
                    )
                    """
                )

                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
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
            "admin",
            None,
        )

        self._create_user(
            "operator-test",
            "operator",
            None,
        )

        self._create_user(
            "controller-a-user",
            "controller",
            "controller-a",
        )

        self._create_user(
            "customer-a-user",
            "customer",
            "customer-a",
        )

        self._create_user(
            "customer-b-user",
            "customer",
            "customer-b",
        )

        self._open_alert(
            "alert-a",
            "controller-a",
            "agent-a",
            "instance-a",
        )

        self._open_alert(
            "alert-b",
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
                            "Password123!"
                        ),
                        role,
                        scope_id,
                    ),
                )

    def _open_alert(
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

    def _get(
        self,
        path,
        username=None,
    ):
        handler = SERVER.DashboardHandler.__new__(
            SERVER.DashboardHandler
        )

        handler.command = "GET"
        handler.path = path
        handler.request_version = "HTTP/1.1"
        handler.close_connection = True

        if username is None:
            handler.headers = {}
        else:
            handler.headers = {
                "Authorization": self._authorization(
                    username
                ),
            }

        response = {
            "code": None,
            "payload": None,
            "forbidden": False,
            "unauthorized": False,
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
            response["unauthorized"] = True

        handler.send_json = send_json
        handler.forbidden = forbidden
        handler.unauthorized = unauthorized

        SERVER.DashboardHandler.do_GET(
            handler
        )

        return response

    def _ids(
        self,
        response,
    ):
        self.assertEqual(
            response["code"],
            200,
            response,
        )

        return {
            item["id"]
            for item
            in response["payload"]["alerts"]
        }

    def test_admin_history_is_global_over_http(self):
        response = self._get(
            "/api/notifications/history",
            "admin-test",
        )

        self.assertEqual(
            self._ids(response),
            {
                "alert-a",
                "alert-b",
            },
        )

    def test_controller_history_is_scoped_over_http(self):
        response = self._get(
            "/api/notifications/history",
            "controller-a-user",
        )

        self.assertEqual(
            self._ids(response),
            {
                "alert-a",
            },
        )

    def test_customer_history_is_scoped_over_http(self):
        response = self._get(
            "/api/notifications/history",
            "customer-a-user",
        )

        self.assertEqual(
            self._ids(response),
            {
                "alert-a",
            },
        )

    def test_history_keeps_resolved_alert_over_http(self):
        ALERTS.resolve_alert(
            self.database,
            "alert-a",
        )

        response = self._get(
            "/api/notifications/history",
            "customer-a-user",
        )

        ids = self._ids(
            response
        )

        self.assertIn(
            "alert-a",
            ids,
        )

        item = next(
            item
            for item
            in response["payload"]["alerts"]
            if item["id"] == "alert-a"
        )

        self.assertEqual(
            item["state"],
            "RESOLVED",
        )

    def test_admin_clear_resolves_all_over_http(self):
        response = self._get(
            "/api/notifications/clear",
            "admin-test",
        )

        self.assertEqual(
            response["code"],
            200,
            response,
        )

        self.assertTrue(
            response["payload"]["ok"]
        )

        self.assertEqual(
            response["payload"]["cleared"],
            2,
        )

        self.assertEqual(
            ALERTS.get_alert(
                self.database,
                "alert-a",
            )["state"],
            "RESOLVED",
        )

        self.assertEqual(
            ALERTS.get_alert(
                self.database,
                "alert-b",
            )["state"],
            "RESOLVED",
        )

    def test_controller_clear_is_scoped_over_http(self):
        response = self._get(
            "/api/notifications/clear",
            "controller-a-user",
        )

        self.assertEqual(
            response["code"],
            200,
            response,
        )

        self.assertEqual(
            response["payload"]["cleared"],
            1,
        )

        self.assertEqual(
            ALERTS.get_alert(
                self.database,
                "alert-a",
            )["state"],
            "RESOLVED",
        )

        self.assertEqual(
            ALERTS.get_alert(
                self.database,
                "alert-b",
            )["state"],
            "OPEN",
        )

    def test_customer_clear_is_scoped_over_http(self):
        response = self._get(
            "/api/notifications/clear",
            "customer-a-user",
        )

        self.assertEqual(
            response["code"],
            200,
            response,
        )

        self.assertEqual(
            response["payload"]["cleared"],
            1,
        )

        self.assertEqual(
            ALERTS.get_alert(
                self.database,
                "alert-a",
            )["state"],
            "RESOLVED",
        )

        self.assertEqual(
            ALERTS.get_alert(
                self.database,
                "alert-b",
            )["state"],
            "OPEN",
        )

    def test_clear_preserves_audit_history_over_http(self):
        response = self._get(
            "/api/notifications/clear",
            "customer-a-user",
        )

        self.assertEqual(
            response["code"],
            200,
            response,
        )

        history = ALERTS.alert_history(
            self.database,
            "alert-a",
        )

        self.assertEqual(
            [
                event["action"]
                for event in history
            ],
            [
                "OPEN",
                "RESOLVE",
            ],
        )

    def test_history_without_authentication_is_rejected(self):
        response = self._get(
            "/api/notifications/history"
        )

        self.assertIn(
            response["code"],
            {
                401,
                403,
            },
            response,
        )

    def test_clear_without_authentication_is_rejected(self):
        response = self._get(
            "/api/notifications/clear"
        )

        self.assertIn(
            response["code"],
            {
                401,
                403,
            },
            response,
        )


if __name__ == "__main__":
    unittest.main()