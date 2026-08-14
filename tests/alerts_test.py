#!/usr/bin/env python3

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT / "database"))

MANAGER_SPEC = importlib.util.spec_from_file_location(
    "manager",
    ROOT / "database" / "manager.py",
)
DB = importlib.util.module_from_spec(MANAGER_SPEC)

# O módulo precisa estar registrado antes da execução.
# Python 3.13/dataclasses consulta sys.modules enquanto
# as classes decoradas estão sendo construídas.
sys.modules["manager"] = DB

MANAGER_SPEC.loader.exec_module(DB)

ALERTS_SPEC = importlib.util.spec_from_file_location(
    "alerts",
    ROOT / "database" / "alerts.py",
)
ALERTS = importlib.util.module_from_spec(ALERTS_SPEC)
ALERTS_SPEC.loader.exec_module(ALERTS)


class AlertsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "data" / "capivara.db"

        DB.initialize(self.database)

        with closing(DB.connect(self.database)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
                    VALUES ('controller1', 'Controller', 'controller')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
                    VALUES ('agent1', 'Agent', 'agent')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO controllers(id, node_id, name)
                    VALUES ('controller1', 'controller1', 'Controller')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO agents(id, controller_id, node_id, name)
                    VALUES ('agent1', 'controller1', 'agent1', 'Agent')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO customers(id, controller_id, name)
                    VALUES ('customer1', 'controller1', 'Cliente')
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
                        'instance1',
                        'agent1',
                        'minecraft',
                        'Minecraft',
                        'controller1',
                        'agent1',
                        'customer1'
                    )
                    """
                )

    def tearDown(self):
        self.temporary.cleanup()

    def open_test_alert(
        self,
        *,
        alert_id="test:instance1",
        rule_id="test-rule",
        level="WARNING",
        message="Alerta de teste",
    ):
        return ALERTS.open_alert(
            self.database,
            alert_id=alert_id,
            rule_id=rule_id,
            level=level,
            message=message,
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

    def test_open_creates_alert_and_event(self):
        result = self.open_test_alert()

        self.assertEqual(result["state"], "OPEN")
        self.assertEqual(result["level"], "WARNING")
        self.assertEqual(result["action"], "OPEN")

        history = ALERTS.alert_history(
            self.database,
            "test:instance1",
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["action"], "OPEN")
        self.assertIsNone(history[0]["old_state"])
        self.assertEqual(history[0]["new_state"], "OPEN")

    def test_repeated_open_is_idempotent(self):
        self.open_test_alert()
        result = self.open_test_alert()

        self.assertEqual(result["action"], "UNCHANGED")

        history = ALERTS.alert_history(
            self.database,
            "test:instance1",
        )

        self.assertEqual(len(history), 1)

    def test_warning_can_escalate_to_critical(self):
        self.open_test_alert()

        result = self.open_test_alert(
            level="CRITICAL",
            message="Falha crítica",
        )

        self.assertEqual(result["state"], "OPEN")
        self.assertEqual(result["level"], "CRITICAL")
        self.assertEqual(result["action"], "ESCALATE")

        history = ALERTS.alert_history(
            self.database,
            "test:instance1",
        )

        self.assertEqual(
            [event["action"] for event in history],
            ["OPEN", "ESCALATE"],
        )

    def test_acknowledge_changes_state_and_records_event(self):
        self.open_test_alert()

        result = ALERTS.acknowledge_alert(
            self.database,
            "test:instance1",
        )

        self.assertEqual(result["state"], "ACKNOWLEDGED")
        self.assertIsNotNone(result["acknowledged_at"])

        history = ALERTS.alert_history(
            self.database,
            "test:instance1",
        )

        self.assertEqual(
            [event["action"] for event in history],
            ["OPEN", "ACK"],
        )

    def test_resolve_is_idempotent(self):
        self.open_test_alert()

        first = ALERTS.resolve_alert(
            self.database,
            "test:instance1",
        )
        second = ALERTS.resolve_alert(
            self.database,
            "test:instance1",
        )

        self.assertEqual(first["state"], "RESOLVED")
        self.assertEqual(second["state"], "RESOLVED")

        history = ALERTS.alert_history(
            self.database,
            "test:instance1",
        )

        self.assertEqual(
            [event["action"] for event in history],
            ["OPEN", "RESOLVE"],
        )

    def test_resolved_alert_can_reopen(self):
        self.open_test_alert()

        ALERTS.resolve_alert(
            self.database,
            "test:instance1",
        )

        result = self.open_test_alert(
            message="Problema voltou",
        )

        self.assertEqual(result["state"], "OPEN")
        self.assertEqual(result["action"], "REOPEN")

        history = ALERTS.alert_history(
            self.database,
            "test:instance1",
        )

        self.assertEqual(
            [event["action"] for event in history],
            ["OPEN", "RESOLVE", "REOPEN"],
        )

    def test_suppressed_alert_can_reopen(self):
        self.open_test_alert()

        suppressed = ALERTS.suppress_alert(
            self.database,
            "test:instance1",
            30,
        )

        self.assertEqual(
            suppressed["state"],
            "SUPPRESSED",
        )
        self.assertIsNotNone(
            suppressed["suppressed_until"],
        )

        reopened = self.open_test_alert(
            message="Problema ocorreu novamente",
        )

        self.assertEqual(reopened["state"], "OPEN")
        self.assertEqual(reopened["action"], "REOPEN")

        history = ALERTS.alert_history(
            self.database,
            "test:instance1",
        )

        self.assertEqual(
            [event["action"] for event in history],
            ["OPEN", "SUPPRESS", "REOPEN"],
        )

    def test_list_active_excludes_resolved_and_suppressed(self):
        self.open_test_alert(
            alert_id="open:instance1",
            rule_id="open-rule",
        )

        self.open_test_alert(
            alert_id="resolved:instance1",
            rule_id="resolved-rule",
        )
        ALERTS.resolve_alert(
            self.database,
            "resolved:instance1",
        )

        self.open_test_alert(
            alert_id="suppressed:instance1",
            rule_id="suppressed-rule",
        )
        ALERTS.suppress_alert(
            self.database,
            "suppressed:instance1",
            30,
        )

        active = ALERTS.list_active(self.database)

        self.assertEqual(
            [alert["id"] for alert in active],
            ["open:instance1"],
        )

    def test_database_prevents_duplicate_active_rule_for_same_target(self):
        self.open_test_alert(
            alert_id="first:instance1",
            rule_id="duplicate-rule",
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.open_test_alert(
                alert_id="second:instance1",
                rule_id="duplicate-rule",
            )


    def test_open_rejects_invalid_level(self):
        with self.assertRaises(ValueError):
            self.open_test_alert(
                level="INVALID",
            )

    def test_open_rejects_invalid_scope(self):
        with self.assertRaises(ValueError):
            ALERTS.open_alert(
                self.database,
                alert_id="invalid-scope",
                rule_id="test-rule",
                level="WARNING",
                message="Teste",
                scope="invalid",
                controller_id="controller1",
            )

    def test_open_rejects_empty_alert_id(self):
        with self.assertRaises(ValueError):
            self.open_test_alert(
                alert_id="",
            )

    def test_open_rejects_empty_rule_id(self):
        with self.assertRaises(ValueError):
            self.open_test_alert(
                rule_id="",
            )

    def test_open_rejects_empty_message(self):
        with self.assertRaises(ValueError):
            self.open_test_alert(
                message="",
            )


    def test_controller_scope_requires_controller(self):
        with self.assertRaises(sqlite3.IntegrityError):
            ALERTS.open_alert(
                self.database,
                alert_id="controller:no-controller",
                rule_id="controller-rule",
                level="WARNING",
                message="Controller ausente",
                scope="controller",
                controller_id=None,
            )

    def test_agent_scope_requires_agent(self):
        with self.assertRaises(sqlite3.IntegrityError):
            ALERTS.open_alert(
                self.database,
                alert_id="agent:no-agent",
                rule_id="agent-rule",
                level="WARNING",
                message="Agent ausente",
                scope="agent",
                controller_id="controller1",
            )

    def test_agent_rejects_controller_mismatch(self):
        with closing(DB.connect(self.database)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
                    VALUES ('controller2', 'Controller 2', 'controller')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO controllers(id, node_id, name)
                    VALUES ('controller2', 'controller2', 'Controller 2')
                    """
                )

        with self.assertRaises(sqlite3.IntegrityError):
            ALERTS.open_alert(
                self.database,
                alert_id="agent:mismatch",
                rule_id="agent-mismatch-rule",
                level="WARNING",
                message="Agent pertence a outro controller",
                scope="agent",
                controller_id="controller2",
                agent_id="agent1",
            )

    def test_instance_scope_requires_complete_hierarchy(self):
        with self.assertRaises(sqlite3.IntegrityError):
            ALERTS.open_alert(
                self.database,
                alert_id="instance:incomplete",
                rule_id="instance-incomplete-rule",
                level="WARNING",
                message="Hierarquia incompleta",
                scope="instance",
                controller_id="controller1",
                agent_id="agent1",
                instance_id="instance1",
            )

    def test_instance_rejects_ownership_mismatch(self):
        with closing(DB.connect(self.database)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO nodes(id, name, role)
                    VALUES ('agent2', 'Agent 2', 'agent')
                    """
                )
                connection.execute(
                    """
                    INSERT INTO agents(id, controller_id, node_id, name)
                    VALUES ('agent2', 'controller1', 'agent2', 'Agent 2')
                    """
                )

        with self.assertRaises(sqlite3.IntegrityError):
            ALERTS.open_alert(
                self.database,
                alert_id="instance:mismatch",
                rule_id="instance-mismatch-rule",
                level="WARNING",
                message="Ownership incorreto",
                scope="instance",
                controller_id="controller1",
                agent_id="agent2",
                node_id="agent2",
                instance_id="instance1",
            )

    def test_instance_accepts_valid_ownership(self):
        result = ALERTS.open_alert(
            self.database,
            alert_id="instance:valid",
            rule_id="instance-valid-rule",
            level="WARNING",
            message="Ownership valido",
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        self.assertEqual(result["state"], "OPEN")
        self.assertEqual(result["controller_id"], "controller1")
        self.assertEqual(result["agent_id"], "agent1")
        self.assertEqual(result["node_id"], "agent1")
        self.assertEqual(result["instance_id"], "instance1")


    def test_list_alerts_filters_by_controller(self):
        self.open_test_alert(
            alert_id="controller-filter",
            rule_id="controller-filter-rule",
        )

        alerts = ALERTS.list_alerts(
            self.database,
            controller_id="controller1",
        )

        self.assertEqual(
            [alert["id"] for alert in alerts],
            ["controller-filter"],
        )

        alerts = ALERTS.list_alerts(
            self.database,
            controller_id="missing-controller",
        )

        self.assertEqual(alerts, [])

    def test_list_alerts_filters_by_agent(self):
        self.open_test_alert(
            alert_id="agent-filter",
            rule_id="agent-filter-rule",
        )

        alerts = ALERTS.list_alerts(
            self.database,
            agent_id="agent1",
        )

        self.assertEqual(
            [alert["id"] for alert in alerts],
            ["agent-filter"],
        )

        alerts = ALERTS.list_alerts(
            self.database,
            agent_id="missing-agent",
        )

        self.assertEqual(alerts, [])

    def test_list_alerts_filters_by_node(self):
        self.open_test_alert(
            alert_id="node-filter",
            rule_id="node-filter-rule",
        )

        alerts = ALERTS.list_alerts(
            self.database,
            node_id="agent1",
        )

        self.assertEqual(
            [alert["id"] for alert in alerts],
            ["node-filter"],
        )

        alerts = ALERTS.list_alerts(
            self.database,
            node_id="missing-node",
        )

        self.assertEqual(alerts, [])

    def test_list_alerts_filters_by_instance(self):
        self.open_test_alert(
            alert_id="instance-filter",
            rule_id="instance-filter-rule",
        )

        alerts = ALERTS.list_alerts(
            self.database,
            instance_id="instance1",
        )

        self.assertEqual(
            [alert["id"] for alert in alerts],
            ["instance-filter"],
        )

        alerts = ALERTS.list_alerts(
            self.database,
            instance_id="missing-instance",
        )

        self.assertEqual(alerts, [])

    def test_list_alerts_combines_scope_and_level_filters(self):
        self.open_test_alert(
            alert_id="warning-instance-filter",
            rule_id="warning-instance-filter-rule",
            level="WARNING",
        )

        self.open_test_alert(
            alert_id="critical-instance-filter",
            rule_id="critical-instance-filter-rule",
            level="CRITICAL",
        )

        alerts = ALERTS.list_alerts(
            self.database,
            scope="instance",
            level="CRITICAL",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        self.assertEqual(
            [alert["id"] for alert in alerts],
            ["critical-instance-filter"],
        )

    def test_list_active_supports_hierarchical_filters(self):
        self.open_test_alert(
            alert_id="active-warning-filter",
            rule_id="active-warning-filter-rule",
            level="WARNING",
        )

        self.open_test_alert(
            alert_id="active-critical-filter",
            rule_id="active-critical-filter-rule",
            level="CRITICAL",
        )

        ALERTS.resolve_alert(
            self.database,
            "active-critical-filter",
        )

        active = ALERTS.list_active(
            self.database,
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        self.assertEqual(
            [alert["id"] for alert in active],
            ["active-warning-filter"],
        )


    def test_list_alerts_rejects_invalid_state(self):
        with self.assertRaisesRegex(
            ValueError,
            "invalid alert state: INVALID",
        ):
            ALERTS.list_alerts(
                self.database,
                state="invalid",
            )

    def test_list_alerts_normalizes_state(self):
        self.open_test_alert(
            alert_id="normalized-state",
            rule_id="normalized-state-rule",
        )

        alerts = ALERTS.list_alerts(
            self.database,
            state=" open ",
        )

        self.assertEqual(
            [alert["id"] for alert in alerts],
            ["normalized-state"],
        )

    def test_list_alerts_filters_resolved_state(self):
        self.open_test_alert(
            alert_id="resolved-state-filter",
            rule_id="resolved-state-filter-rule",
        )

        ALERTS.resolve_alert(
            self.database,
            "resolved-state-filter",
        )

        alerts = ALERTS.list_alerts(
            self.database,
            state="RESOLVED",
        )

        self.assertEqual(
            [alert["id"] for alert in alerts],
            ["resolved-state-filter"],
        )

        self.assertEqual(
            alerts[0]["state"],
            "RESOLVED",
        )

    def test_list_alerts_filters_suppressed_state(self):
        self.open_test_alert(
            alert_id="suppressed-state-filter",
            rule_id="suppressed-state-filter-rule",
        )

        ALERTS.suppress_alert(
            self.database,
            "suppressed-state-filter",
            30,
        )

        alerts = ALERTS.list_alerts(
            self.database,
            state="SUPPRESSED",
        )

        self.assertEqual(
            [alert["id"] for alert in alerts],
            ["suppressed-state-filter"],
        )

        self.assertEqual(
            alerts[0]["state"],
            "SUPPRESSED",
        )


    def test_list_alerts_limit(self):
        for index in range(5):
            self.open_test_alert(
                alert_id=f"pagination-limit-{index}",
                rule_id=f"pagination-limit-rule-{index}",
            )

        all_alerts = ALERTS.list_alerts(
            self.database,
        )

        limited = ALERTS.list_alerts(
            self.database,
            limit=2,
        )

        self.assertEqual(
            [alert["id"] for alert in limited],
            [alert["id"] for alert in all_alerts[:2]],
        )

    def test_list_alerts_offset_without_limit(self):
        for index in range(5):
            self.open_test_alert(
                alert_id=f"pagination-offset-{index}",
                rule_id=f"pagination-offset-rule-{index}",
            )

        all_alerts = ALERTS.list_alerts(
            self.database,
        )

        paged = ALERTS.list_alerts(
            self.database,
            offset=2,
        )

        self.assertEqual(
            [alert["id"] for alert in paged],
            [alert["id"] for alert in all_alerts[2:]],
        )

    def test_list_alerts_limit_and_offset(self):
        for index in range(6):
            self.open_test_alert(
                alert_id=f"pagination-window-{index}",
                rule_id=f"pagination-window-rule-{index}",
            )

        all_alerts = ALERTS.list_alerts(
            self.database,
        )

        paged = ALERTS.list_alerts(
            self.database,
            limit=2,
            offset=2,
        )

        self.assertEqual(
            [alert["id"] for alert in paged],
            [alert["id"] for alert in all_alerts[2:4]],
        )

    def test_list_alerts_pagination_combines_with_filters(self):
        for index in range(4):
            self.open_test_alert(
                alert_id=f"pagination-filter-warning-{index}",
                rule_id=f"pagination-filter-warning-rule-{index}",
                level="WARNING",
            )

        self.open_test_alert(
            alert_id="pagination-filter-critical",
            rule_id="pagination-filter-critical-rule",
            level="CRITICAL",
        )

        warnings = ALERTS.list_alerts(
            self.database,
            level="WARNING",
        )

        paged = ALERTS.list_alerts(
            self.database,
            level="WARNING",
            limit=2,
            offset=1,
        )

        self.assertEqual(
            [alert["id"] for alert in paged],
            [alert["id"] for alert in warnings[1:3]],
        )

        self.assertTrue(
            all(alert["level"] == "WARNING" for alert in paged)
        )

    def test_list_alerts_offset_beyond_result_returns_empty(self):
        for index in range(2):
            self.open_test_alert(
                alert_id=f"pagination-beyond-{index}",
                rule_id=f"pagination-beyond-rule-{index}",
            )

        alerts = ALERTS.list_alerts(
            self.database,
            offset=100,
        )

        self.assertEqual(alerts, [])

    def test_list_alerts_rejects_invalid_limit(self):
        invalid_values = (
            0,
            -1,
            "2",
            True,
        )

        for value in invalid_values:
            with self.subTest(limit=value):
                with self.assertRaises(ValueError):
                    ALERTS.list_alerts(
                        self.database,
                        limit=value,
                    )

    def test_list_alerts_rejects_invalid_offset(self):
        invalid_values = (
            -1,
            "1",
            True,
        )

        for value in invalid_values:
            with self.subTest(offset=value):
                with self.assertRaises(ValueError):
                    ALERTS.list_alerts(
                        self.database,
                        offset=value,
                    )

    def test_list_alerts_default_pagination_is_backward_compatible(self):
        for index in range(3):
            self.open_test_alert(
                alert_id=f"pagination-default-{index}",
                rule_id=f"pagination-default-rule-{index}",
            )

        default_result = ALERTS.list_alerts(
            self.database,
        )

        explicit_result = ALERTS.list_alerts(
            self.database,
            limit=None,
            offset=0,
        )

        self.assertEqual(
            [alert["id"] for alert in explicit_result],
            [alert["id"] for alert in default_result],
        )


    def test_count_alerts_empty_database_returns_zero(self):
        self.assertEqual(
            ALERTS.count_alerts(self.database),
            0,
        )

    def test_count_alerts_matches_list_alerts_total(self):
        for index in range(5):
            self.open_test_alert(
                alert_id=f"count-total-{index}",
                rule_id=f"count-total-rule-{index}",
            )

        alerts = ALERTS.list_alerts(
            self.database,
        )

        total = ALERTS.count_alerts(
            self.database,
        )

        self.assertEqual(
            total,
            len(alerts),
        )

    def test_count_alerts_supports_state_filter(self):
        self.open_test_alert(
            alert_id="count-state-open",
            rule_id="count-state-open-rule",
        )

        self.open_test_alert(
            alert_id="count-state-resolved",
            rule_id="count-state-resolved-rule",
        )

        ALERTS.resolve_alert(
            self.database,
            "count-state-resolved",
        )

        self.open_test_alert(
            alert_id="count-state-suppressed",
            rule_id="count-state-suppressed-rule",
        )

        ALERTS.suppress_alert(
            self.database,
            "count-state-suppressed",
            30,
        )

        self.assertEqual(
            ALERTS.count_alerts(
                self.database,
                state="OPEN",
            ),
            1,
        )

        self.assertEqual(
            ALERTS.count_alerts(
                self.database,
                state="RESOLVED",
            ),
            1,
        )

        self.assertEqual(
            ALERTS.count_alerts(
                self.database,
                state="SUPPRESSED",
            ),
            1,
        )

    def test_count_alerts_normalizes_and_validates_state(self):
        self.open_test_alert(
            alert_id="count-normalized-state",
            rule_id="count-normalized-state-rule",
        )

        self.assertEqual(
            ALERTS.count_alerts(
                self.database,
                state=" open ",
            ),
            1,
        )

        with self.assertRaisesRegex(
            ValueError,
            "invalid alert state: INVALID",
        ):
            ALERTS.count_alerts(
                self.database,
                state="invalid",
            )

    def test_count_alerts_combines_filters(self):
        ALERTS.open_alert(
            self.database,
            alert_id="count-combined-match",
            rule_id="count-combined-match-rule",
            level="WARNING",
            message="Count combined match",
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        ALERTS.open_alert(
            self.database,
            alert_id="count-combined-other-level",
            rule_id="count-combined-other-level-rule",
            level="CRITICAL",
            message="Count combined other level",
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        total = ALERTS.count_alerts(
            self.database,
            level="WARNING",
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        self.assertEqual(total, 1)

    def test_count_alerts_matches_filtered_list_alerts(self):
        for index in range(4):
            self.open_test_alert(
                alert_id=f"count-filter-warning-{index}",
                rule_id=f"count-filter-warning-rule-{index}",
                level="WARNING",
            )

        for index in range(2):
            self.open_test_alert(
                alert_id=f"count-filter-critical-{index}",
                rule_id=f"count-filter-critical-rule-{index}",
                level="CRITICAL",
            )

        alerts = ALERTS.list_alerts(
            self.database,
            level="WARNING",
        )

        total = ALERTS.count_alerts(
            self.database,
            level="WARNING",
        )

        self.assertEqual(
            total,
            len(alerts),
        )


    def test_list_active_limit(self):
        for index in range(5):
            self.open_test_alert(
                alert_id=f"active-pagination-limit-{index}",
                rule_id=f"active-pagination-limit-rule-{index}",
            )

        all_active = ALERTS.list_active(
            self.database,
        )

        limited = ALERTS.list_active(
            self.database,
            limit=2,
        )

        self.assertEqual(
            [alert["id"] for alert in limited],
            [alert["id"] for alert in all_active[:2]],
        )

    def test_list_active_offset_without_limit(self):
        for index in range(5):
            self.open_test_alert(
                alert_id=f"active-pagination-offset-{index}",
                rule_id=f"active-pagination-offset-rule-{index}",
            )

        all_active = ALERTS.list_active(
            self.database,
        )

        paged = ALERTS.list_active(
            self.database,
            offset=2,
        )

        self.assertEqual(
            [alert["id"] for alert in paged],
            [alert["id"] for alert in all_active[2:]],
        )

    def test_list_active_limit_and_offset(self):
        for index in range(6):
            self.open_test_alert(
                alert_id=f"active-pagination-window-{index}",
                rule_id=f"active-pagination-window-rule-{index}",
            )

        all_active = ALERTS.list_active(
            self.database,
        )

        paged = ALERTS.list_active(
            self.database,
            limit=2,
            offset=2,
        )

        self.assertEqual(
            [alert["id"] for alert in paged],
            [alert["id"] for alert in all_active[2:4]],
        )

    def test_list_active_pagination_preserves_priority_order(self):
        for index in range(3):
            self.open_test_alert(
                alert_id=f"active-priority-warning-{index}",
                rule_id=f"active-priority-warning-rule-{index}",
                level="WARNING",
            )

        for index in range(2):
            self.open_test_alert(
                alert_id=f"active-priority-critical-{index}",
                rule_id=f"active-priority-critical-rule-{index}",
                level="CRITICAL",
            )

        all_active = ALERTS.list_active(
            self.database,
        )

        self.assertEqual(
            [alert["level"] for alert in all_active[:2]],
            ["CRITICAL", "CRITICAL"],
        )

        first_page = ALERTS.list_active(
            self.database,
            limit=2,
        )

        self.assertEqual(
            [alert["id"] for alert in first_page],
            [alert["id"] for alert in all_active[:2]],
        )

        self.assertTrue(
            all(
                alert["level"] == "CRITICAL"
                for alert in first_page
            )
        )

    def test_list_active_pagination_combines_with_filters(self):
        for index in range(4):
            self.open_test_alert(
                alert_id=f"active-pagination-filter-warning-{index}",
                rule_id=f"active-pagination-filter-warning-rule-{index}",
                level="WARNING",
            )

        self.open_test_alert(
            alert_id="active-pagination-filter-critical",
            rule_id="active-pagination-filter-critical-rule",
            level="CRITICAL",
        )

        warnings = ALERTS.list_active(
            self.database,
            level="WARNING",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        paged = ALERTS.list_active(
            self.database,
            level="WARNING",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
            limit=2,
            offset=1,
        )

        self.assertEqual(
            [alert["id"] for alert in paged],
            [alert["id"] for alert in warnings[1:3]],
        )

        self.assertTrue(
            all(alert["level"] == "WARNING" for alert in paged)
        )

    def test_list_active_offset_beyond_result_returns_empty(self):
        for index in range(2):
            self.open_test_alert(
                alert_id=f"active-pagination-beyond-{index}",
                rule_id=f"active-pagination-beyond-rule-{index}",
            )

        active = ALERTS.list_active(
            self.database,
            offset=100,
        )

        self.assertEqual(active, [])

    def test_list_active_rejects_invalid_limit(self):
        invalid_values = (
            0,
            -1,
            "2",
            True,
        )

        for value in invalid_values:
            with self.subTest(limit=value):
                with self.assertRaises(ValueError):
                    ALERTS.list_active(
                        self.database,
                        limit=value,
                    )

    def test_list_active_rejects_invalid_offset(self):
        invalid_values = (
            -1,
            "1",
            True,
        )

        for value in invalid_values:
            with self.subTest(offset=value):
                with self.assertRaises(ValueError):
                    ALERTS.list_active(
                        self.database,
                        offset=value,
                    )

    def test_list_active_default_pagination_is_backward_compatible(self):
        for index in range(3):
            self.open_test_alert(
                alert_id=f"active-pagination-default-{index}",
                rule_id=f"active-pagination-default-rule-{index}",
            )

        default_result = ALERTS.list_active(
            self.database,
        )

        explicit_result = ALERTS.list_active(
            self.database,
            limit=None,
            offset=0,
        )

        self.assertEqual(
            [alert["id"] for alert in explicit_result],
            [alert["id"] for alert in default_result],
        )


    def test_count_active_empty_database_returns_zero(self):
        self.assertEqual(
            ALERTS.count_active(self.database),
            0,
        )

    def test_count_active_includes_open_and_acknowledged(self):
        self.open_test_alert(
            alert_id="count-active-open",
            rule_id="count-active-open-rule",
        )

        self.open_test_alert(
            alert_id="count-active-acknowledged",
            rule_id="count-active-acknowledged-rule",
        )

        ALERTS.acknowledge_alert(
            self.database,
            "count-active-acknowledged",
        )

        self.assertEqual(
            ALERTS.count_active(self.database),
            2,
        )

    def test_count_active_excludes_resolved_and_suppressed(self):
        self.open_test_alert(
            alert_id="count-active-open-only",
            rule_id="count-active-open-only-rule",
        )

        self.open_test_alert(
            alert_id="count-active-resolved",
            rule_id="count-active-resolved-rule",
        )

        ALERTS.resolve_alert(
            self.database,
            "count-active-resolved",
        )

        self.open_test_alert(
            alert_id="count-active-suppressed",
            rule_id="count-active-suppressed-rule",
        )

        ALERTS.suppress_alert(
            self.database,
            "count-active-suppressed",
            30,
        )

        self.assertEqual(
            ALERTS.count_active(self.database),
            1,
        )

    def test_count_active_matches_list_active_total(self):
        for index in range(5):
            self.open_test_alert(
                alert_id=f"count-active-total-{index}",
                rule_id=f"count-active-total-rule-{index}",
            )

        active = ALERTS.list_active(
            self.database,
        )

        total = ALERTS.count_active(
            self.database,
        )

        self.assertEqual(
            total,
            len(active),
        )

    def test_count_active_supports_level_filter(self):
        for index in range(3):
            self.open_test_alert(
                alert_id=f"count-active-warning-{index}",
                rule_id=f"count-active-warning-rule-{index}",
                level="WARNING",
            )

        for index in range(2):
            self.open_test_alert(
                alert_id=f"count-active-critical-{index}",
                rule_id=f"count-active-critical-rule-{index}",
                level="CRITICAL",
            )

        self.assertEqual(
            ALERTS.count_active(
                self.database,
                level="WARNING",
            ),
            3,
        )

        self.assertEqual(
            ALERTS.count_active(
                self.database,
                level="CRITICAL",
            ),
            2,
        )

    def test_count_active_combines_hierarchical_filters(self):
        ALERTS.open_alert(
            self.database,
            alert_id="count-active-hierarchy-match",
            rule_id="count-active-hierarchy-match-rule",
            level="WARNING",
            message="Count active hierarchy match",
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        total = ALERTS.count_active(
            self.database,
            level="WARNING",
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        self.assertEqual(total, 1)

        missing = ALERTS.count_active(
            self.database,
            level="WARNING",
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="missing-instance",
        )

        self.assertEqual(missing, 0)

    def test_count_active_matches_filtered_list_active(self):
        for index in range(4):
            self.open_test_alert(
                alert_id=f"count-active-filter-warning-{index}",
                rule_id=f"count-active-filter-warning-rule-{index}",
                level="WARNING",
            )

        self.open_test_alert(
            alert_id="count-active-filter-critical",
            rule_id="count-active-filter-critical-rule",
            level="CRITICAL",
        )

        active = ALERTS.list_active(
            self.database,
            level="WARNING",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        total = ALERTS.count_active(
            self.database,
            level="WARNING",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
        )

        self.assertEqual(
            total,
            len(active),
        )


    def test_list_alerts_page_returns_page_contract(self):
        for index in range(5):
            self.open_test_alert(
                alert_id=f"page-contract-alert-{index}",
                rule_id=f"page-contract-alert-rule-{index}",
            )

        page = ALERTS.list_alerts_page(
            self.database,
            limit=2,
            offset=1,
        )

        self.assertEqual(
            set(page),
            {"items", "total", "limit", "offset"},
        )

        self.assertEqual(page["total"], 5)
        self.assertEqual(page["limit"], 2)
        self.assertEqual(page["offset"], 1)
        self.assertEqual(len(page["items"]), 2)

    def test_list_alerts_page_total_is_not_paginated(self):
        for index in range(6):
            self.open_test_alert(
                alert_id=f"page-total-alert-{index}",
                rule_id=f"page-total-alert-rule-{index}",
            )

        page = ALERTS.list_alerts_page(
            self.database,
            limit=2,
            offset=2,
        )

        self.assertEqual(page["total"], 6)
        self.assertEqual(len(page["items"]), 2)

        expected = ALERTS.list_alerts(
            self.database,
            limit=2,
            offset=2,
        )

        self.assertEqual(
            [alert["id"] for alert in page["items"]],
            [alert["id"] for alert in expected],
        )

    def test_list_alerts_page_preserves_filters(self):
        for index in range(4):
            self.open_test_alert(
                alert_id=f"page-filter-warning-{index}",
                rule_id=f"page-filter-warning-rule-{index}",
                level="WARNING",
            )

        self.open_test_alert(
            alert_id="page-filter-critical",
            rule_id="page-filter-critical-rule",
            level="CRITICAL",
        )

        page = ALERTS.list_alerts_page(
            self.database,
            level="WARNING",
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
            limit=2,
            offset=1,
        )

        self.assertEqual(page["total"], 4)
        self.assertEqual(len(page["items"]), 2)

        self.assertTrue(
            all(
                alert["level"] == "WARNING"
                for alert in page["items"]
            )
        )

    def test_list_alerts_page_default_contract_is_backward_compatible(self):
        for index in range(3):
            self.open_test_alert(
                alert_id=f"page-default-alert-{index}",
                rule_id=f"page-default-alert-rule-{index}",
            )

        page = ALERTS.list_alerts_page(
            self.database,
        )

        alerts = ALERTS.list_alerts(
            self.database,
        )

        self.assertEqual(page["limit"], None)
        self.assertEqual(page["offset"], 0)
        self.assertEqual(page["total"], len(alerts))

        self.assertEqual(
            [alert["id"] for alert in page["items"]],
            [alert["id"] for alert in alerts],
        )

    def test_list_active_page_returns_page_contract(self):
        for index in range(5):
            self.open_test_alert(
                alert_id=f"active-page-contract-{index}",
                rule_id=f"active-page-contract-rule-{index}",
            )

        page = ALERTS.list_active_page(
            self.database,
            limit=2,
            offset=1,
        )

        self.assertEqual(
            set(page),
            {"items", "total", "limit", "offset"},
        )

        self.assertEqual(page["total"], 5)
        self.assertEqual(page["limit"], 2)
        self.assertEqual(page["offset"], 1)
        self.assertEqual(len(page["items"]), 2)

    def test_list_active_page_total_excludes_inactive_alerts(self):
        self.open_test_alert(
            alert_id="active-page-open",
            rule_id="active-page-open-rule",
        )

        self.open_test_alert(
            alert_id="active-page-acknowledged",
            rule_id="active-page-acknowledged-rule",
        )

        ALERTS.acknowledge_alert(
            self.database,
            "active-page-acknowledged",
        )

        self.open_test_alert(
            alert_id="active-page-resolved",
            rule_id="active-page-resolved-rule",
        )

        ALERTS.resolve_alert(
            self.database,
            "active-page-resolved",
        )

        self.open_test_alert(
            alert_id="active-page-suppressed",
            rule_id="active-page-suppressed-rule",
        )

        ALERTS.suppress_alert(
            self.database,
            "active-page-suppressed",
            30,
        )

        page = ALERTS.list_active_page(
            self.database,
            limit=1,
        )

        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 1)

        self.assertTrue(
            all(
                alert["state"] in {"OPEN", "ACKNOWLEDGED"}
                for alert in page["items"]
            )
        )

    def test_list_active_page_preserves_priority_and_filters(self):
        for index in range(3):
            self.open_test_alert(
                alert_id=f"active-page-warning-{index}",
                rule_id=f"active-page-warning-rule-{index}",
                level="WARNING",
            )

        for index in range(2):
            self.open_test_alert(
                alert_id=f"active-page-critical-{index}",
                rule_id=f"active-page-critical-rule-{index}",
                level="CRITICAL",
            )

        page = ALERTS.list_active_page(
            self.database,
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
            limit=2,
            offset=0,
        )

        self.assertEqual(page["total"], 5)

        self.assertEqual(
            [alert["level"] for alert in page["items"]],
            ["CRITICAL", "CRITICAL"],
        )

        expected = ALERTS.list_active(
            self.database,
            controller_id="controller1",
            agent_id="agent1",
            node_id="agent1",
            instance_id="instance1",
            limit=2,
        )

        self.assertEqual(
            [alert["id"] for alert in page["items"]],
            [alert["id"] for alert in expected],
        )

    def test_page_contract_rejects_invalid_pagination(self):
        functions = (
            ALERTS.list_alerts_page,
            ALERTS.list_active_page,
        )

        for function in functions:
            with self.subTest(
                function=function.__name__,
                parameter="limit",
            ):
                with self.assertRaises(ValueError):
                    function(
                        self.database,
                        limit=0,
                    )

            with self.subTest(
                function=function.__name__,
                parameter="offset",
            ):
                with self.assertRaises(ValueError):
                    function(
                        self.database,
                        offset=-1,
                    )


    def test_query_filter_builder_empty_contract(self):
        clauses, parameters = ALERTS._build_query_filters()

        self.assertEqual(clauses, [])
        self.assertEqual(parameters, [])

    def test_query_filter_builder_normalizes_validated_filters(self):
        clauses, parameters = ALERTS._build_query_filters(
            state=" open ",
            level=" warning ",
            scope=" INSTANCE ",
        )

        self.assertEqual(
            clauses,
            [
                "state=?",
                "level=?",
                "scope=?",
            ],
        )

        self.assertEqual(
            parameters,
            [
                "OPEN",
                "WARNING",
                "instance",
            ],
        )

    def test_query_filter_builder_preserves_hierarchical_parameter_order(self):
        clauses, parameters = ALERTS._build_query_filters(
            controller_id="controller1",
            agent_id="agent1",
            node_id="node1",
            instance_id="instance1",
        )

        self.assertEqual(
            clauses,
            [
                "controller_id=?",
                "agent_id=?",
                "node_id=?",
                "instance_id=?",
            ],
        )

        self.assertEqual(
            parameters,
            [
                "controller1",
                "agent1",
                "node1",
                "instance1",
            ],
        )

    def test_query_filter_builder_combines_all_general_filters(self):
        clauses, parameters = ALERTS._build_query_filters(
            state="ACKNOWLEDGED",
            level="CRITICAL",
            scope="instance",
            controller_id="controller1",
            agent_id="agent1",
            node_id="node1",
            instance_id="instance1",
        )

        self.assertEqual(
            clauses,
            [
                "state=?",
                "level=?",
                "scope=?",
                "controller_id=?",
                "agent_id=?",
                "node_id=?",
                "instance_id=?",
            ],
        )

        self.assertEqual(
            parameters,
            [
                "ACKNOWLEDGED",
                "CRITICAL",
                "instance",
                "controller1",
                "agent1",
                "node1",
                "instance1",
            ],
        )

    def test_query_filter_builder_active_only_uses_active_state_clause(self):
        clauses, parameters = ALERTS._build_query_filters(
            active_only=True,
        )

        self.assertEqual(
            clauses,
            [
                "state IN ('OPEN', 'ACKNOWLEDGED')",
            ],
        )

        self.assertEqual(parameters, [])

    def test_query_filter_builder_active_only_ignores_explicit_state(self):
        clauses, parameters = ALERTS._build_query_filters(
            state="RESOLVED",
            active_only=True,
        )

        self.assertEqual(
            clauses,
            [
                "state IN ('OPEN', 'ACKNOWLEDGED')",
            ],
        )

        self.assertEqual(parameters, [])

    def test_query_filter_builder_active_only_combines_other_filters(self):
        clauses, parameters = ALERTS._build_query_filters(
            level=" critical ",
            scope=" INSTANCE ",
            controller_id="controller1",
            agent_id="agent1",
            node_id="node1",
            instance_id="instance1",
            active_only=True,
        )

        self.assertEqual(
            clauses,
            [
                "state IN ('OPEN', 'ACKNOWLEDGED')",
                "level=?",
                "scope=?",
                "controller_id=?",
                "agent_id=?",
                "node_id=?",
                "instance_id=?",
            ],
        )

        self.assertEqual(
            parameters,
            [
                "CRITICAL",
                "instance",
                "controller1",
                "agent1",
                "node1",
                "instance1",
            ],
        )

    def test_query_filter_builder_rejects_invalid_validated_filters(self):
        invalid_cases = (
            (
                {"state": "invalid"},
                "invalid alert state: INVALID",
            ),
            (
                {"level": "invalid"},
                "invalid alert level: INVALID",
            ),
            (
                {"scope": "invalid"},
                "invalid alert scope: invalid",
            ),
        )

        for arguments, message in invalid_cases:
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(
                    ValueError,
                    message,
                ):
                    ALERTS._build_query_filters(
                        **arguments,
                    )


if __name__ == "__main__":
    unittest.main()
