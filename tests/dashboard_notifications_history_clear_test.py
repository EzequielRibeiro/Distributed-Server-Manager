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
    "capivara_dashboard_history_clear_test",
    ROOT / "dashboard" / "server.py",
)

SERVER = importlib.util.module_from_spec(
    spec
)

spec.loader.exec_module(
    SERVER
)


class DashboardNotificationHistoryClearTest(
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
                    VALUES ('controller-a', 'Controller A', 'controller')
                    """
                )

                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
                    VALUES ('controller-b', 'Controller B', 'controller')
                    """
                )

                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
                    VALUES ('agent-a', 'Agent A', 'agent')
                    """
                )

                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
                    VALUES ('agent-b', 'Agent B', 'agent')
                    """
                )

                connection.execute(
                    """
                    INSERT INTO controllers(id, node_id, name)
                    VALUES ('controller-a', 'controller-a', 'Controller A')
                    """
                )

                connection.execute(
                    """
                    INSERT INTO controllers(id, node_id, name)
                    VALUES ('controller-b', 'controller-b', 'Controller B')
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

        self._open(
            "alert-a",
            "controller-a",
            "agent-a",
            "instance-a",
        )

        self._open(
            "alert-b",
            "controller-b",
            "agent-b",
            "instance-b",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _open(
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

    def test_admin_history_is_global(self):
        payload = SERVER.api_notification_history(
            {
                "role": "admin",
                "scope_id": "",
            },
            database_path=self.database,
        )

        self.assertEqual(
            {
                item["id"]
                for item in payload["alerts"]
            },
            {
                "alert-a",
                "alert-b",
            },
        )

    def test_controller_history_is_scoped(self):
        payload = SERVER.api_notification_history(
            {
                "role": "controller",
                "scope_id": "controller-a",
            },
            database_path=self.database,
        )

        self.assertEqual(
            {
                item["id"]
                for item in payload["alerts"]
            },
            {
                "alert-a",
            },
        )

    def test_customer_history_is_scoped(self):
        payload = SERVER.api_notification_history(
            {
                "role": "customer",
                "scope_id": "customer-a",
            },
            database_path=self.database,
        )

        self.assertEqual(
            {
                item["id"]
                for item in payload["alerts"]
            },
            {
                "alert-a",
            },
        )

    def test_history_keeps_resolved_alert(self):
        ALERTS.resolve_alert(
            self.database,
            "alert-a",
        )

        payload = SERVER.api_notification_history(
            {
                "role": "customer",
                "scope_id": "customer-a",
            },
            database_path=self.database,
        )

        item = next(
            item
            for item in payload["alerts"]
            if item["id"] == "alert-a"
        )

        self.assertEqual(
            item["state"],
            "RESOLVED",
        )

    def test_customer_clear_resolves_only_own_alert(self):
        payload = SERVER.api_notification_clear(
            {
                "role": "customer",
                "scope_id": "customer-a",
            },
            database_path=self.database,
        )

        self.assertTrue(
            payload["ok"]
        )

        self.assertEqual(
            payload["cleared"],
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

    def test_controller_clear_resolves_only_own_scope(self):
        payload = SERVER.api_notification_clear(
            {
                "role": "controller",
                "scope_id": "controller-a",
            },
            database_path=self.database,
        )

        self.assertEqual(
            payload["cleared"],
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

    def test_admin_clear_resolves_all_active_alerts(self):
        payload = SERVER.api_notification_clear(
            {
                "role": "admin",
                "scope_id": "",
            },
            database_path=self.database,
        )

        self.assertEqual(
            payload["cleared"],
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

    def test_clear_preserves_alert_event_history(self):
        SERVER.api_notification_clear(
            {
                "role": "customer",
                "scope_id": "customer-a",
            },
            database_path=self.database,
        )

        history = ALERTS.alert_history(
            self.database,
            "alert-a",
        )

        self.assertEqual(
            [
                item["action"]
                for item in history
            ],
            [
                "OPEN",
                "RESOLVE",
            ],
        )


if __name__ == "__main__":
    unittest.main()