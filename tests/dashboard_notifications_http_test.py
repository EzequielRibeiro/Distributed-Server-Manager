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
    "capivara_dashboard_notifications_http_test",
    ROOT / "dashboard" / "server.py",
)

SERVER = importlib.util.module_from_spec(
    spec
)

spec.loader.exec_module(
    SERVER
)


class DashboardNotificationsHTTPTest(
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
            alert_id="alert-instance-a",
            controller_id="controller-a",
            agent_id="agent-a",
            instance_id="instance-a",
            scope="instance",
        )

        self._open_alert(
            alert_id="alert-instance-b",
            controller_id="controller-b",
            agent_id="agent-b",
            instance_id="instance-b",
            scope="instance",
        )

        self._open_alert(
            alert_id="alert-controller-a",
            controller_id="controller-a",
            agent_id=None,
            instance_id=None,
            scope="controller",
        )

        self._open_alert(
            alert_id="alert-controller-b",
            controller_id="controller-b",
            agent_id=None,
            instance_id=None,
            scope="controller",
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
        *,
        alert_id,
        controller_id,
        agent_id,
        instance_id,
        scope,
    ):
        ALERTS.open_alert(
            self.database,
            alert_id=alert_id,
            rule_id=f"rule.{alert_id}",
            level="WARNING",
            message=f"Mensagem {alert_id}",
            scope=scope,
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
        username=None,
    ):
        handler = SERVER.DashboardHandler.__new__(
            SERVER.DashboardHandler
        )

        handler.command = "GET"
        handler.path = "/api/notifications"
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

    def test_admin_sees_all_alerts(self):
        ids = self._ids(
            self._request(
                username="admin-test",
            )
        )

        self.assertEqual(
            ids,
            {
                "alert-instance-a",
                "alert-instance-b",
                "alert-controller-a",
                "alert-controller-b",
            },
        )

    def test_operator_sees_all_alerts(self):
        ids = self._ids(
            self._request(
                username="operator-test",
            )
        )

        self.assertEqual(
            ids,
            {
                "alert-instance-a",
                "alert-instance-b",
                "alert-controller-a",
                "alert-controller-b",
            },
        )

    def test_controller_sees_only_own_scope(self):
        ids = self._ids(
            self._request(
                username="controller-a-user",
            )
        )

        self.assertEqual(
            ids,
            {
                "alert-instance-a",
                "alert-controller-a",
            },
        )

    def test_customer_sees_only_own_instance(self):
        ids = self._ids(
            self._request(
                username="customer-a-user",
            )
        )

        self.assertEqual(
            ids,
            {
                "alert-instance-a",
            },
        )

        self.assertNotIn(
            "alert-controller-a",
            ids,
        )

        self.assertNotIn(
            "alert-instance-b",
            ids,
        )

    def test_other_customer_sees_only_other_instance(self):
        ids = self._ids(
            self._request(
                username="customer-b-user",
            )
        )

        self.assertEqual(
            ids,
            {
                "alert-instance-b",
            },
        )

    def test_resolved_alert_disappears(self):
        ALERTS.resolve_alert(
            self.database,
            "alert-instance-a",
        )

        ids = self._ids(
            self._request(
                username="admin-test",
            )
        )

        self.assertNotIn(
            "alert-instance-a",
            ids,
        )

    def test_acknowledged_alert_remains_with_ack_true(self):
        ALERTS.acknowledge_alert(
            self.database,
            "alert-instance-a",
        )

        response = self._request(
            username="customer-a-user",
        )

        ids = self._ids(
            response
        )

        self.assertIn(
            "alert-instance-a",
            ids,
        )

        item = next(
            item
            for item
            in response["payload"]["alerts"]
            if item["id"]
            == "alert-instance-a"
        )

        self.assertTrue(
            item["ack"]
        )

    def test_missing_authentication_is_rejected(self):
        response = self._request()

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