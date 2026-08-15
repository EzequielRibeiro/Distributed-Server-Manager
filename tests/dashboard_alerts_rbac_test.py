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
    "capivara_dashboard_server_alert_rbac_test",
    ROOT / "dashboard" / "server.py",
)

SERVER = importlib.util.module_from_spec(
    spec
)

spec.loader.exec_module(
    SERVER
)


class DashboardAlertRBACConnectionTest(
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

        self._open_alert(
            alert_id="alert-instance-a",
            controller_id="controller-a",
            agent_id="agent-a",
            node_id="agent-a",
            instance_id="instance-a",
            scope="instance",
        )

        self._open_alert(
            alert_id="alert-instance-b",
            controller_id="controller-b",
            agent_id="agent-b",
            node_id="agent-b",
            instance_id="instance-b",
            scope="instance",
        )

        self._open_alert(
            alert_id="alert-controller-a",
            controller_id="controller-a",
            agent_id=None,
            node_id=None,
            instance_id=None,
            scope="controller",
        )

        self._open_alert(
            alert_id="alert-controller-b",
            controller_id="controller-b",
            agent_id=None,
            node_id=None,
            instance_id=None,
            scope="controller",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _open_alert(
        self,
        *,
        alert_id,
        controller_id,
        agent_id,
        node_id,
        instance_id,
        scope,
    ):
        return ALERTS.open_alert(
            self.database,
            alert_id=alert_id,
            rule_id=f"rule.{alert_id}",
            level="WARNING",
            message=f"Mensagem {alert_id}",
            scope=scope,
            controller_id=controller_id,
            agent_id=agent_id,
            node_id=node_id,
            instance_id=instance_id,
        )

    def alert_ids(
        self,
        user,
    ):
        payload = SERVER.api_notifications(
            user,
            database_path=self.database,
        )

        return {
            item["id"]
            for item in payload["alerts"]
        }

    def test_admin_sees_all_active_alerts(self):
        ids = self.alert_ids(
            {
                "username": "admin",
                "role": "admin",
                "scope_id": "",
            }
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

    def test_operator_sees_all_active_alerts(self):
        ids = self.alert_ids(
            {
                "username": "operator",
                "role": "operator",
                "scope_id": "",
            }
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

    def test_controller_is_limited_to_own_controller(self):
        ids = self.alert_ids(
            {
                "username": "controller-user-a",
                "role": "controller",
                "scope_id": "controller-a",
            }
        )

        self.assertEqual(
            ids,
            {
                "alert-instance-a",
                "alert-controller-a",
            },
        )

        self.assertNotIn(
            "alert-instance-b",
            ids,
        )

        self.assertNotIn(
            "alert-controller-b",
            ids,
        )

    def test_customer_sees_only_own_instance_alerts(self):
        ids = self.alert_ids(
            {
                "username": "customer-user-a",
                "role": "customer",
                "scope_id": "customer-a",
            }
        )

        self.assertEqual(
            ids,
            {
                "alert-instance-a",
            },
        )

    def test_customer_cannot_access_other_customer_alert(self):
        user = {
            "username": "customer-user-a",
            "role": "customer",
            "scope_id": "customer-a",
        }

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-b",
        )

        self.assertFalse(
            SERVER._can_access_alert(
                user,
                alert,
                database_path=self.database,
            )
        )

    def test_customer_cannot_access_controller_alert(self):
        user = {
            "username": "customer-user-a",
            "role": "customer",
            "scope_id": "customer-a",
        }

        alert = ALERTS.get_alert(
            self.database,
            "alert-controller-a",
        )

        self.assertFalse(
            SERVER._can_access_alert(
                user,
                alert,
                database_path=self.database,
            )
        )

    def test_customer_can_access_own_instance_alert(self):
        user = {
            "username": "customer-user-a",
            "role": "customer",
            "scope_id": "customer-a",
        }

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-a",
        )

        self.assertTrue(
            SERVER._can_access_alert(
                user,
                alert,
                database_path=self.database,
            )
        )

    def test_controller_cannot_access_other_controller_alert(self):
        user = {
            "username": "controller-user-a",
            "role": "controller",
            "scope_id": "controller-a",
        }

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-b",
        )

        self.assertFalse(
            SERVER._can_access_alert(
                user,
                alert,
                database_path=self.database,
            )
        )

    def test_admin_can_access_any_alert(self):
        user = {
            "username": "admin",
            "role": "admin",
            "scope_id": "",
        }

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-b",
        )

        self.assertTrue(
            SERVER._can_access_alert(
                user,
                alert,
                database_path=self.database,
            )
        )

    def test_authorized_ack_changes_alert_state(self):
        user = {
            "username": "customer-user-a",
            "role": "customer",
            "scope_id": "customer-a",
        }

        alert = ALERTS.get_alert(
            self.database,
            "alert-instance-a",
        )

        self.assertTrue(
            SERVER._can_access_alert(
                user,
                alert,
                database_path=self.database,
            )
        )

        result = ALERTS.acknowledge_alert(
            self.database,
            alert["id"],
        )

        self.assertEqual(
            result["state"],
            "ACKNOWLEDGED",
        )

        ids = self.alert_ids(
            user
        )

        self.assertIn(
            "alert-instance-a",
            ids,
        )

        payload = SERVER.api_notifications(
            user,
            database_path=self.database,
        )

        item = next(
            item
            for item in payload["alerts"]
            if item["id"]
            == "alert-instance-a"
        )

        self.assertTrue(
            item["ack"]
        )

    def test_resolved_alert_disappears_from_dashboard(self):
        ALERTS.resolve_alert(
            self.database,
            "alert-instance-a",
        )

        ids = self.alert_ids(
            {
                "username": "admin",
                "role": "admin",
                "scope_id": "",
            }
        )

        self.assertNotIn(
            "alert-instance-a",
            ids,
        )


if __name__ == "__main__":
    unittest.main()