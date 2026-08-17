#!/usr/bin/env python3
"""Real PostgreSQL integration tests for Capivara DSM.

These tests are opt-in and require:

    DSM_POSTGRESQL_INTEGRATION=1
    DSM_DATABASE_HOST
    DSM_DATABASE_PORT
    DSM_DATABASE_NAME
    DSM_DATABASE_USER
    DSM_DATABASE_PASSWORD_FILE
    DSM_DATABASE_TLS

The target database must already have the Capivara migrations applied.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE_DIR = ROOT / "database"

sys.path.insert(
    0,
    str(DATABASE_DIR),
)


from backend import DatabaseConfig

import postgresql_engine


INTEGRATION_ENABLED = (
    os.environ.get(
        "DSM_POSTGRESQL_INTEGRATION",
        "",
    ).strip().lower()
    in {
        "1",
        "true",
        "yes",
        "on",
    }
)


@unittest.skipUnless(
    INTEGRATION_ENABLED,
    "PostgreSQL integration tests are disabled",
)
class PostgreSQLIntegrationTest(
    unittest.TestCase
):

    def setUp(self):
        self.prefix = (
            "it-"
            + uuid.uuid4().hex[:12]
        )

        self.config = DatabaseConfig(
            driver="postgresql",
            database=os.environ.get(
                "DSM_DATABASE_NAME",
                "capivara_test",
            ),
            host=os.environ.get(
                "DSM_DATABASE_HOST",
                "localhost",
            ),
            port=int(
                os.environ.get(
                    "DSM_DATABASE_PORT",
                    "5432",
                )
            ),
            user=os.environ.get(
                "DSM_DATABASE_USER",
                "postgres",
            ),
            password_file=os.environ.get(
                "DSM_DATABASE_PASSWORD_FILE"
            ),
            tls_mode=os.environ.get(
                "DSM_DATABASE_TLS",
                "disable",
            ),
            connect_timeout=5,
        )

        self.connection = (
            postgresql_engine.connect(
                self.config
            )
        )

        self._create_base_fixture()

    def tearDown(self):
        try:
            self.connection.rollback()

            pattern = (
                self.prefix
                + "%"
            )

            # Dependency order is intentional.
            self.connection.execute(
                """
                DELETE FROM alert_events
                WHERE alert_id LIKE %s
                """,
                (pattern,),
            )

            self.connection.execute(
                """
                DELETE FROM alerts
                WHERE id LIKE %s
                """,
                (pattern,),
            )

            self.connection.execute(
                """
                DELETE FROM instance_ports
                WHERE instance_id LIKE %s
                """,
                (pattern,),
            )

            self.connection.execute(
                """
                DELETE FROM instance_contracts
                WHERE instance_id LIKE %s
                   OR contract_id LIKE %s
                """,
                (
                    pattern,
                    pattern,
                ),
            )

            self.connection.execute(
                """
                DELETE FROM service_contracts
                WHERE id LIKE %s
                """,
                (pattern,),
            )

            self.connection.execute(
                """
                DELETE FROM instances
                WHERE id LIKE %s
                """,
                (pattern,),
            )

            self.connection.execute(
                """
                DELETE FROM customers
                WHERE id LIKE %s
                """,
                (pattern,),
            )

            self.connection.execute(
                """
                DELETE FROM agents
                WHERE id LIKE %s
                """,
                (pattern,),
            )

            self.connection.execute(
                """
                DELETE FROM controllers
                WHERE id LIKE %s
                """,
                (pattern,),
            )

            self.connection.execute(
                """
                DELETE FROM nodes
                WHERE id LIKE %s
                """,
                (pattern,),
            )

            self.connection.commit()

        finally:
            self.connection.close()

    # =========================================================
    # Fixtures
    # =========================================================

    def _id(
        self,
        suffix: str,
    ) -> str:
        return (
            f"{self.prefix}-{suffix}"
        )

    def _create_base_fixture(self):
        self.controller_node = self._id(
            "controller-node"
        )

        self.agent_node = self._id(
            "agent-node"
        )

        self.controller_id = self._id(
            "controller"
        )

        self.agent_id = self._id(
            "agent"
        )

        self.customer_id = self._id(
            "customer"
        )

        self.connection.execute(
            """
            INSERT INTO nodes(
                id,
                name,
                role,
                status
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                self.controller_node,
                "Integration Controller Node",
                "controller",
                "active",
            ),
        )

        self.connection.execute(
            """
            INSERT INTO nodes(
                id,
                name,
                role,
                status
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                self.agent_node,
                "Integration Agent Node",
                "agent",
                "active",
            ),
        )

        self.connection.execute(
            """
            INSERT INTO controllers(
                id,
                node_id,
                name
            )
            VALUES (%s, %s, %s)
            """,
            (
                self.controller_id,
                self.controller_node,
                "Integration Controller",
            ),
        )

        self.connection.execute(
            """
            INSERT INTO agents(
                id,
                controller_id,
                node_id,
                name,
                status
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                self.agent_id,
                self.controller_id,
                self.agent_node,
                "Integration Agent",
                "active",
            ),
        )

        self.connection.execute(
            """
            INSERT INTO customers(
                id,
                controller_id,
                name,
                status
            )
            VALUES (%s, %s, %s, %s)
            """,
            (
                self.customer_id,
                self.controller_id,
                "Integration Customer",
                "active",
            ),
        )

        self.connection.commit()

    def _create_instance(
        self,
        suffix: str,
        *,
        game_id: str = "dayz",
    ) -> str:
        instance_id = self._id(
            suffix
        )

        self.connection.execute(
            """
            INSERT INTO instances(
                id,
                node_id,
                controller_id,
                agent_id,
                customer_id,
                game_id,
                name,
                status
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'pending'
            )
            """,
            (
                instance_id,
                self.agent_node,
                self.controller_id,
                self.agent_id,
                self.customer_id,
                game_id,
                suffix,
            ),
        )

        self.connection.commit()

        return instance_id

    # =========================================================
    # Ownership
    # =========================================================

    def test_valid_instance_ownership(self):
        instance_id = (
            self._create_instance(
                "instance-valid"
            )
        )

        row = self.connection.execute(
            """
            SELECT
                controller_id,
                agent_id,
                customer_id,
                node_id
            FROM instances
            WHERE id = %s
            """,
            (instance_id,),
        ).fetchone()

        self.assertEqual(
            row["controller_id"],
            self.controller_id,
        )

        self.assertEqual(
            row["agent_id"],
            self.agent_id,
        )

        self.assertEqual(
            row["customer_id"],
            self.customer_id,
        )

        self.assertEqual(
            row["node_id"],
            self.agent_node,
        )

    def test_invalid_instance_ownership_is_rejected(self):
        instance_id = self._id(
            "instance-invalid"
        )

        with self.assertRaises(
            Exception
        ):
            self.connection.execute(
                """
                INSERT INTO instances(
                    id,
                    node_id,
                    controller_id,
                    agent_id,
                    customer_id,
                    game_id,
                    name,
                    status
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'dayz',
                    'Invalid ownership',
                    'pending'
                )
                """,
                (
                    instance_id,
                    self.controller_node,
                    self.controller_id,
                    self.agent_id,
                    self.customer_id,
                ),
            )

        self.connection.rollback()

    # =========================================================
    # Service contracts
    # =========================================================

    def test_contract_instance_limit_is_enforced(self):
        first_instance = (
            self._create_instance(
                "contract-instance-1"
            )
        )

        second_instance = (
            self._create_instance(
                "contract-instance-2"
            )
        )

        contract_id = self._id(
            "contract"
        )

        self.connection.execute(
            """
            INSERT INTO service_contracts(
                id,
                customer_id,
                game_id,
                status,
                instance_limit
            )
            VALUES (
                %s,
                %s,
                'dayz',
                'active',
                1
            )
            """,
            (
                contract_id,
                self.customer_id,
            ),
        )

        self.connection.execute(
            """
            INSERT INTO instance_contracts(
                instance_id,
                contract_id
            )
            VALUES (%s, %s)
            """,
            (
                first_instance,
                contract_id,
            ),
        )

        self.connection.commit()

        with self.assertRaises(
            Exception
        ):
            self.connection.execute(
                """
                INSERT INTO instance_contracts(
                    instance_id,
                    contract_id
                )
                VALUES (%s, %s)
                """,
                (
                    second_instance,
                    contract_id,
                ),
            )

        self.connection.rollback()

    # =========================================================
    # Network ports
    # =========================================================

    def test_node_port_collision_is_rejected(self):
        first_instance = (
            self._create_instance(
                "port-instance-1"
            )
        )

        second_instance = (
            self._create_instance(
                "port-instance-2"
            )
        )

        self.connection.execute(
            """
            INSERT INTO instance_ports(
                instance_id,
                node_id,
                name,
                protocol,
                port
            )
            VALUES (
                %s,
                %s,
                'game',
                'udp',
                2302
            )
            """,
            (
                first_instance,
                self.agent_node,
            ),
        )

        self.connection.commit()

        with self.assertRaises(
            Exception
        ):
            self.connection.execute(
                """
                INSERT INTO instance_ports(
                    instance_id,
                    node_id,
                    name,
                    protocol,
                    port
                )
                VALUES (
                    %s,
                    %s,
                    'game',
                    'udp',
                    2302
                )
                """,
                (
                    second_instance,
                    self.agent_node,
                ),
            )

        self.connection.rollback()

    # =========================================================
    # Alerts
    # =========================================================

    def test_invalid_alert_scope_is_rejected(self):
        alert_id = self._id(
            "alert-invalid"
        )

        with self.assertRaises(
            Exception
        ):
            self.connection.execute(
                """
                INSERT INTO alerts(
                    id,
                    scope,
                    controller_id,
                    rule_id,
                    level,
                    state,
                    message
                )
                VALUES (
                    %s,
                    'agent',
                    %s,
                    'integration-rule',
                    'WARNING',
                    'OPEN',
                    'Missing agent id'
                )
                """,
                (
                    alert_id,
                    self.controller_id,
                ),
            )

        self.connection.rollback()

    def test_active_alert_deduplication_and_reopen(self):
        instance_id = (
            self._create_instance(
                "alert-instance"
            )
        )

        first_alert = self._id(
            "alert-first"
        )

        second_alert = self._id(
            "alert-second"
        )

        rule_id = (
            self._id(
                "rule"
            )
        )

        self.connection.execute(
            """
            INSERT INTO alerts(
                id,
                scope,
                controller_id,
                agent_id,
                node_id,
                instance_id,
                rule_id,
                level,
                state,
                message
            )
            VALUES (
                %s,
                'instance',
                %s,
                %s,
                %s,
                %s,
                %s,
                'CRITICAL',
                'OPEN',
                'First occurrence'
            )
            """,
            (
                first_alert,
                self.controller_id,
                self.agent_id,
                self.agent_node,
                instance_id,
                rule_id,
            ),
        )

        self.connection.commit()

        # A second active occurrence of the same rule and
        # logical target must be rejected.
        with self.assertRaises(
            Exception
        ):
            self.connection.execute(
                """
                INSERT INTO alerts(
                    id,
                    scope,
                    controller_id,
                    agent_id,
                    node_id,
                    instance_id,
                    rule_id,
                    level,
                    state,
                    message
                )
                VALUES (
                    %s,
                    'instance',
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'CRITICAL',
                    'OPEN',
                    'Duplicate active occurrence'
                )
                """,
                (
                    second_alert,
                    self.controller_id,
                    self.agent_id,
                    self.agent_node,
                    instance_id,
                    rule_id,
                ),
            )

        self.connection.rollback()

        # Resolve the first occurrence.
        self.connection.execute(
            """
            UPDATE alerts
            SET
                state = 'RESOLVED',
                resolved_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (first_alert,),
        )

        self.connection.commit()

        # Once RESOLVED, a new occurrence is valid.
        self.connection.execute(
            """
            INSERT INTO alerts(
                id,
                scope,
                controller_id,
                agent_id,
                node_id,
                instance_id,
                rule_id,
                level,
                state,
                message
            )
            VALUES (
                %s,
                'instance',
                %s,
                %s,
                %s,
                %s,
                %s,
                'CRITICAL',
                'OPEN',
                'New occurrence after resolution'
            )
            """,
            (
                second_alert,
                self.controller_id,
                self.agent_id,
                self.agent_node,
                instance_id,
                rule_id,
            ),
        )

        self.connection.commit()

        count = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM alerts
            WHERE rule_id = %s
            """,
            (rule_id,),
        ).fetchone()

        self.assertEqual(
            count["count"],
            2,
        )


if __name__ == "__main__":
    unittest.main()
