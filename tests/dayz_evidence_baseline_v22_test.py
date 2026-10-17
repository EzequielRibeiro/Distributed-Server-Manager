"""Baseline v22 command-parameter compatibility tests."""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "database"))
from baseline_upgrade_engine import _upgrade_instance_evidence_parameters, _column_names


class InstanceEvidenceBaselineUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.backend = SimpleNamespace(name="sqlite")
        self.db.execute(
            "CREATE TABLE agent_instance_commands (command_id TEXT PRIMARY KEY, action TEXT NOT NULL)"
        )
        self.db.execute(
            "INSERT INTO agent_instance_commands(command_id,action) VALUES ('existing','status')"
        )

    def tearDown(self):
        self.db.close()

    def test_additive_and_idempotent(self):
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.assertIn("parameters_json", _column_names(self.backend, self.db, "agent_instance_commands"))
        row = self.db.execute(
            "SELECT command_id,action,parameters_json FROM agent_instance_commands"
        ).fetchone()
        self.assertEqual(("existing", "status", None), tuple(row))

    def test_legacy_action_check_still_blocks_evidence(self):
        """Track the remaining migration gap; adding a column is insufficient."""
        self.db.execute("DROP TABLE agent_instance_commands")
        self.db.execute(
            "CREATE TABLE agent_instance_commands ("
            "command_id TEXT PRIMARY KEY, "
            "action TEXT NOT NULL CHECK (action IN "
            "('status','doctor','start','stop','restart','remove')))"
        )
        self.db.commit()
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.db.execute("INSERT INTO agent_instance_commands(command_id,action,parameters_json) VALUES ('evidence','systemd_lifecycle_evidence','{}')")
        self.assertIn('parameters_json', _column_names(self.backend, self.db, 'agent_instance_commands'))

    def test_legacy_schema_preserves_rows_indexes_and_foreign_keys(self):
        """Baseline v22 must not silently destroy existing relational metadata."""
        self.db.execute("DROP TABLE agent_instance_commands")
        self.db.execute("CREATE TABLE agents (id TEXT PRIMARY KEY)")
        self.db.execute("CREATE TABLE instances (id TEXT PRIMARY KEY)")
        self.db.execute("INSERT INTO agents VALUES ('agent-1')")
        self.db.execute("INSERT INTO instances VALUES ('instance-1')")
        self.db.execute(
            "CREATE TABLE agent_instance_commands ("
            "command_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, "
            "instance_id TEXT NOT NULL, action TEXT NOT NULL "
            "CHECK (action IN ('status','doctor','start','stop','restart','remove')), "
            "FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE, "
            "FOREIGN KEY(instance_id) REFERENCES instances(id) ON DELETE CASCADE)"
        )
        self.db.execute(
            "CREATE INDEX idx_agent_instance_commands_agent_status "
            "ON agent_instance_commands(agent_id,action)"
        )
        self.db.execute(
            "INSERT INTO agent_instance_commands VALUES "
            "('existing','agent-1','instance-1','status')"
        )
        before_fk = [tuple(row) for row in self.db.execute(
            "PRAGMA foreign_key_list(agent_instance_commands)"
        )]
        before_indexes = [row[1] for row in self.db.execute(
            "PRAGMA index_list(agent_instance_commands)"
        )]
        self.db.commit()
        self.db.execute("PRAGMA foreign_keys=ON")
        self.assertEqual(1, self.db.execute("PRAGMA foreign_keys").fetchone()[0])
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.assertEqual(
            1,
            self.db.execute("PRAGMA foreign_keys").fetchone()[0],
            "migration must restore the original foreign-key enforcement",
        )
        self.assertEqual(before_fk, [tuple(row) for row in self.db.execute(
            "PRAGMA foreign_key_list(agent_instance_commands)"
        )])
        self.assertEqual(before_indexes, [row[1] for row in self.db.execute(
            "PRAGMA index_list(agent_instance_commands)"
        )])
        self.assertEqual(1, self.db.execute(
            "SELECT COUNT(*) FROM agent_instance_commands WHERE command_id='existing'"
        ).fetchone()[0])
        self.assertEqual([], self.db.execute("PRAGMA foreign_key_check").fetchall())

    def test_unknown_action_constraint_fails_closed(self):
        self.db.execute("DROP TABLE agent_instance_commands")
        self.db.execute(
            "CREATE TABLE agent_instance_commands ("
            "command_id TEXT PRIMARY KEY, action TEXT NOT NULL "
            "CHECK (action IN ('status','custom_action')))"
        )
        self.db.execute(
            "INSERT INTO agent_instance_commands VALUES ('existing','status')"
        )
        self.db.commit()
        with self.assertRaisesRegex(Exception, "unknown SQLite command action constraint"):
            _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.assertEqual(
            1,
            self.db.execute(
                "SELECT COUNT(*) FROM agent_instance_commands "
                "WHERE command_id='existing'"
            ).fetchone()[0],
        )
        self.assertNotIn(
            "parameters_json",
            _column_names(self.backend, self.db, "agent_instance_commands"),
        )

    def test_legacy_upgrade_idempotent_after_rebuild(self):
        self.db.execute("DROP TABLE agent_instance_commands")
        self.db.execute(
            "CREATE TABLE agent_instance_commands ("
            "command_id TEXT PRIMARY KEY, action TEXT NOT NULL "
            "CHECK (action IN ('status','doctor','start','stop','restart','remove')))"
        )
        self.db.execute(
            "INSERT INTO agent_instance_commands VALUES ('existing','status')"
        )
        self.db.commit()
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.db.execute(
            "INSERT INTO agent_instance_commands(command_id,action,parameters_json) "
            "VALUES ('evidence','systemd_lifecycle_evidence','{}')"
        )
        self.assertEqual(
            2,
            self.db.execute("SELECT COUNT(*) FROM agent_instance_commands").fetchone()[0],
        )

    def test_canonical_sqlite_schema_with_status_check_is_idempotent(self):
        self.db.execute("DROP TABLE agent_instance_commands")
        schema = Path(__file__).resolve().parents[1] / "database/schemas/sqlite.sql"
        self.db.executescript(schema.read_text(encoding="utf-8"))
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.db.execute(
            "INSERT INTO agent_instance_commands "
            "(command_id,agent_id,instance_id,action,status) "
            "VALUES ('evidence','agent-1','instance-1',"
            "'systemd_lifecycle_evidence','queued')"
        )
        self.assertIn(
            "parameters_json",
            _column_names(self.backend, self.db, "agent_instance_commands"),
        )

    def test_extra_action_check_rejected_after_v22_without_data_loss(self):
        self.db.execute("DROP TABLE agent_instance_commands")
        self.db.execute(
            "CREATE TABLE agent_instance_commands ("
            "command_id TEXT PRIMARY KEY, action TEXT NOT NULL "
            "CHECK (action IN ('status','doctor','save','start','stop',"
            "'restart','remove','systemd_lifecycle_evidence')), "
            "status TEXT CHECK (status IN "
            "('queued','delivered','completed','failed')), "
            "CHECK (action <> 'systemd_lifecycle_evidence'))"
        )
        self.db.execute(
            "INSERT INTO agent_instance_commands(command_id,action,status) "
            "VALUES ('existing','status','queued')"
        )
        self.db.commit()
        with self.assertRaisesRegex(
            Exception, "unknown SQLite evidence action constraint"
        ):
            _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.assertEqual(
            1,
            self.db.execute(
                "SELECT COUNT(*) FROM agent_instance_commands"
            ).fetchone()[0],
        )

    def test_legacy_trigger_fails_closed_without_data_loss(self):
        self.db.execute("DROP TABLE agent_instance_commands")
        self.db.execute(
            "CREATE TABLE agent_instance_commands ("
            "command_id TEXT PRIMARY KEY, action TEXT NOT NULL "
            "CHECK (action IN ('status','doctor','start','stop','restart','remove')))"
        )
        self.db.execute(
            "INSERT INTO agent_instance_commands VALUES ('existing','status')"
        )
        self.db.execute(
            "CREATE TRIGGER protect_commands BEFORE DELETE ON agent_instance_commands "
            "BEGIN SELECT RAISE(ABORT, 'protected'); END"
        )
        self.db.commit()
        with self.assertRaisesRegex(Exception, "triggers require manual review"):
            _upgrade_instance_evidence_parameters(self.backend, self.db)
        self.assertEqual(
            1,
            self.db.execute(
                "SELECT COUNT(*) FROM agent_instance_commands WHERE command_id='existing'"
            ).fetchone()[0],
        )
        self.assertEqual(
            1,
            self.db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                "AND name='protect_commands'"
            ).fetchone()[0],
        )

    def test_missing_table_fails_closed(self):
        self.db.execute("DROP TABLE agent_instance_commands")
        with self.assertRaisesRegex(Exception, "table is missing"):
            _upgrade_instance_evidence_parameters(self.backend, self.db)




class PostgreSQLInstanceEvidenceGuardTest(unittest.TestCase):
    """Reject PostgreSQL CHECK predicates that a literal-set parser could miss."""

    def test_recognized_legacy_action_check_upgrades(self):
        from unittest.mock import patch

        class Result:
            def __init__(self, rows=None, row=None):
                self.rows = rows
                self.row = row

            def fetchall(self):
                return self.rows

            def fetchone(self):
                return self.row

        class Connection:
            def __init__(self):
                self.statements = []

            def execute(self, sql, params=None):
                self.statements.append(sql)
                if "pg_constraint" in sql:
                    return Result(rows=[{
                        "conname": "agent_instance_commands_action_check",
                        "definition": (
                            "CHECK ((action = ANY (ARRAY['status'::text,"
                            "'doctor'::text,'start'::text,'stop'::text,"
                            "'restart'::text,'remove'::text])))"
                        ),
                    }])
                if "information_schema.columns" in sql:
                    return Result(row={
                        "data_type": "character varying",
                        "character_maximum_length": 16,
                    })
                return Result()

        connection = Connection()
        with patch(
            "baseline_upgrade_engine._table_names",
            return_value={"agent_instance_commands"},
        ), patch(
            "baseline_upgrade_engine._column_names",
            return_value={"action", "parameters_json"},
        ):
            _upgrade_instance_evidence_parameters(
                SimpleNamespace(name="postgresql"), connection
            )
        statements = "\\n".join(connection.statements)
        self.assertIn("DROP CONSTRAINT", statements)
        self.assertIn("systemd_lifecycle_evidence", statements)
        self.assertIn("ALTER COLUMN action TYPE TEXT", statements)

    def test_compound_action_check_fails_before_ddl(self):
        from unittest.mock import patch

        class Result:
            def fetchall(self):
                return [{
                    "conname": "legacy_action_check",
                    "definition": (
                        "CHECK ((action = ANY (ARRAY['status'::text,"
                        "'doctor'::text,'start'::text,'stop'::text,"
                        "'restart'::text,'remove'::text])) "
                        "AND action <> 'systemd_lifecycle_evidence'::text)"
                    ),
                }]

        class Connection:
            def __init__(self):
                self.statements = []

            def execute(self, sql, params=None):
                self.statements.append(sql)
                if "pg_constraint" in sql:
                    return Result()
                raise AssertionError("DDL must not run on an unknown CHECK")

        connection = Connection()
        with patch(
            "baseline_upgrade_engine._table_names",
            return_value={"agent_instance_commands"},
        ):
            with self.assertRaisesRegex(Exception, "compound PostgreSQL"):
                _upgrade_instance_evidence_parameters(
                    SimpleNamespace(name="postgresql"), connection
                )
        self.assertEqual(1, len(connection.statements))



class MySQLInstanceEvidenceGuardTest(unittest.TestCase):
    """Exercise the MySQL preflight without a live MySQL server."""

    def test_legacy_varchar_widened_before_parameters_column(self):
        from unittest.mock import patch

        state = {"width": 16, "parameters": False}
        ddl = []

        class Cursor:
            def execute(self, sql, params=None):
                pass

            def fetchone(self):
                return {"data_type": "varchar", "max_length": state["width"]}

            def fetchall(self):
                return []

            def close(self):
                pass

        class Connection:
            def cursor(self, dictionary=False):
                return Cursor()

        def execute_script(backend, connection, sql):
            ddl.append(sql)
            if "MODIFY COLUMN action VARCHAR(64) NOT NULL" in sql:
                state["width"] = 64
            elif "ADD COLUMN parameters_json LONGTEXT" in sql:
                state["parameters"] = True
            else:
                raise AssertionError(sql)

        def columns(backend, connection, table):
            return {"action", "parameters_json"} if state["parameters"] else {"action"}

        connection = Connection()
        with patch(
            "baseline_upgrade_engine._table_names",
            return_value={"agent_instance_commands"},
        ), patch(
            "baseline_upgrade_engine._column_names",
            side_effect=columns,
        ), patch(
            "baseline_upgrade_engine._execute_script",
            side_effect=execute_script,
        ):
            _upgrade_instance_evidence_parameters(
                SimpleNamespace(name="mysql"), connection
            )
            _upgrade_instance_evidence_parameters(
                SimpleNamespace(name="mysql"), connection
            )
        self.assertEqual(2, len(ddl))
        self.assertIn("MODIFY COLUMN action VARCHAR(64) NOT NULL", ddl[0])
        self.assertIn("ADD COLUMN parameters_json LONGTEXT", ddl[1])

    def test_mysql_widening_verification_fails_closed(self):
        from unittest.mock import patch

        statements = []

        class Cursor:
            def execute(self, sql, params=None):
                pass

            def fetchone(self):
                return {"data_type": "varchar", "max_length": 16}

            def fetchall(self):
                return []

            def close(self):
                pass

        class Connection:
            def cursor(self, dictionary=False):
                return Cursor()

        with patch(
            "baseline_upgrade_engine._table_names",
            return_value={"agent_instance_commands"},
        ), patch(
            "baseline_upgrade_engine._execute_script",
            side_effect=lambda backend, connection, sql: statements.append(sql),
        ):
            with self.assertRaisesRegex(Exception, "width upgrade incomplete"):
                _upgrade_instance_evidence_parameters(
                    SimpleNamespace(name="mysql"), Connection()
                )
        self.assertEqual(1, len(statements))
        self.assertIn("MODIFY COLUMN action VARCHAR(64)", statements[0])
        self.assertNotIn("parameters_json", statements[0])

    def test_enum_action_rejected_before_schema_change(self):
        from unittest.mock import patch

        class Cursor:
            def execute(self, sql, params=None):
                pass

            def fetchone(self):
                return {"data_type": "enum", "max_length": 64}

            def fetchall(self):
                return []

            def close(self):
                pass

        class Connection:
            def cursor(self, dictionary=False):
                return Cursor()

        with patch(
            "baseline_upgrade_engine._table_names",
            return_value={"agent_instance_commands"},
        ):
            with self.assertRaisesRegex(Exception, "ENUM requires a reviewed migration"):
                _upgrade_instance_evidence_parameters(
                    SimpleNamespace(name="mysql"), Connection()
                )

    def test_unknown_varchar_width_rejected(self):
        from unittest.mock import patch

        class Cursor:
            def execute(self, sql, params=None):
                pass

            def fetchone(self):
                return {"data_type": "varchar", "max_length": None}

            def fetchall(self):
                return []

            def close(self):
                pass

        class Connection:
            def cursor(self, dictionary=False):
                return Cursor()

        with patch(
            "baseline_upgrade_engine._table_names",
            return_value={"agent_instance_commands"},
        ):
            with self.assertRaisesRegex(Exception, "width is unknown"):
                _upgrade_instance_evidence_parameters(
                    SimpleNamespace(name="mysql"), Connection()
                )

    def test_numeric_action_type_rejected_even_without_width(self):
        from unittest.mock import patch

        class Cursor:
            def execute(self, sql, params=None):
                pass

            def fetchone(self):
                return {"data_type": "int", "max_length": None}

            def fetchall(self):
                return []

            def close(self):
                pass

        class Connection:
            def cursor(self, dictionary=False):
                return Cursor()

        with patch(
            "baseline_upgrade_engine._table_names",
            return_value={"agent_instance_commands"},
        ):
            with self.assertRaisesRegex(Exception, "unsupported MySQL evidence action"):
                _upgrade_instance_evidence_parameters(
                    SimpleNamespace(name="mysql"), Connection()
                )

    def test_canonical_mysql_action_check_upgrade_and_replay(self):
        from unittest.mock import patch

        state = {"width": 16, "parameters": False, "action_check": "legacy"}
        statements = []
        legacy = "('status','doctor','start','stop','restart','remove')"
        expanded = "('status','doctor','start','stop','restart','remove','systemd_lifecycle_evidence')"
        def mysql_check(actions):
            return "(`action` in (" + ",".join(
                "_utf8mb4" + value for value in actions[1:-1].split(",")
            ) + "))"

        class Cursor:
            def __init__(self):
                self.query = ""

            def execute(self, sql, params=None):
                self.query = sql

            def fetchone(self):
                if "CHARACTER_MAXIMUM_LENGTH" in self.query:
                    return {"data_type": "varchar", "max_length": state["width"]}
                if "CHECK_CLAUSE" in self.query:
                    return {"check_clause": mysql_check(expanded)}
                if "SELECT VERSION()" in self.query:
                    return {"version": "8.4.0"}
                raise AssertionError(self.query)

            def fetchall(self):
                if state["action_check"] == "absent":
                    return []
                actions = legacy if state["action_check"] == "legacy" else expanded
                return [{
                    "constraint_name": "chk_agent_instance_commands_v3_action",
                    "check_clause": mysql_check(actions),
                }]

            def close(self):
                pass

        class Connection:
            def cursor(self, dictionary=False):
                return Cursor()

        def execute_script(backend, connection, sql):
            statements.append(sql)
            if "MODIFY COLUMN action VARCHAR(64)" in sql:
                state["width"] = 64
            elif ("DROP CHECK chk_agent_instance_commands_v3_action" in sql
                  and "ADD CONSTRAINT chk_agent_instance_commands_v3_action" in sql):
                state["action_check"] = "expanded"
            elif "ADD COLUMN parameters_json LONGTEXT" in sql:
                state["parameters"] = True
            else:
                raise AssertionError(sql)

        def columns(backend, connection, table):
            return {"action", "parameters_json"} if state["parameters"] else {"action"}

        with patch("baseline_upgrade_engine._table_names", return_value={"agent_instance_commands"}), patch(
            "baseline_upgrade_engine._column_names", side_effect=columns
        ), patch("baseline_upgrade_engine._execute_script", side_effect=execute_script):
            _upgrade_instance_evidence_parameters(SimpleNamespace(name="mysql"), Connection())
            _upgrade_instance_evidence_parameters(SimpleNamespace(name="mysql"), Connection())

        self.assertEqual(3, len(statements))
        self.assertEqual("expanded", state["action_check"])
        self.assertEqual(64, state["width"])
        self.assertTrue(state["parameters"])

    def test_action_check_rejected_before_schema_change(self):
        from unittest.mock import patch

        class Cursor:
            def __init__(self):
                self.query = ""

            def execute(self, sql, params=None):
                self.query = sql

            def fetchone(self):
                return {"data_type": "varchar", "max_length": 64}

            def fetchall(self):
                return [{
                    "constraint_name": "legacy_action_check",
                    "check_clause": "action IN ('status','start','stop')",
                }]

            def close(self):
                pass

        class Connection:
            def cursor(self, dictionary=False):
                return Cursor()

        with patch(
            "baseline_upgrade_engine._table_names",
            return_value={"agent_instance_commands"},
        ):
            with self.assertRaisesRegex(Exception, "explicit review"):
                _upgrade_instance_evidence_parameters(
                    SimpleNamespace(name="mysql"), Connection()
                )


if __name__ == "__main__":
    unittest.main()
