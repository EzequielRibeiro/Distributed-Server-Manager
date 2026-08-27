#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from discord_integration_schema import discord_integration_ddl


class CustomerDiscordIntegrationTest(unittest.TestCase):
    def test_sqlite_schema_is_executable_and_customer_scoped(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY)")
        connection.executescript(discord_integration_ddl("sqlite"))
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        self.assertTrue({
            "customer_discord_connections",
            "customer_discord_instance_bindings",
            "customer_discord_preferences",
            "customer_discord_oauth_states",
        }.issubset(tables))
        connection.execute("INSERT INTO customers(id) VALUES(1)")
        connection.execute(
            "INSERT INTO customer_discord_connections(id,customer_id,guild_id,guild_name,is_default) VALUES(?,?,?,?,?)",
            ("discord-1", 1, "guild-1", "Comunidade", 1),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO customer_discord_connections(id,customer_id,guild_id,guild_name,is_default) VALUES(?,?,?,?,?)",
                ("discord-2", 999, "guild-2", "Inválida", 1),
            )

    def test_postgresql_flags_use_portable_numeric_contract(self):
        sql = discord_integration_ddl("postgresql")
        self.assertIn("is_default SMALLINT", sql)
        self.assertIn("enabled SMALLINT", sql)
        self.assertNotIn("is_default BOOLEAN", sql)

    def test_discord_backend_is_generic_not_dayz_specific(self):
        source = (ROOT / "dashboard" / "customer_discord_http.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("dayz", source)
        for token in (
            "server.started", "player.connected", "backup.completed",
            '"status"', '"players"', '"restart"',
        ):
            self.assertIn(token, source)

    def test_customer_navigation_exposes_expected_areas(self):
        source = (ROOT / "dashboard" / "web" / "customer-navigation.js").read_text(encoding="utf-8")
        for path in (
            "/customer.html",
            "/customer-backups.html",
            "/customer-integrations.html",
            "/customer-members.html",
            "/customer-account.html",
        ):
            self.assertIn(path, source)
        self.assertNotIn("/customer-change-password.html", source)

    def test_oauth_callback_does_not_require_browser_basic_auth(self):
        source = (ROOT / "dashboard" / "customer_discord_oauth_http.py").read_text(encoding="utf-8")
        self.assertIn("customer_discord_oauth_states", source)
        self.assertIn("DELETE FROM customer_discord_oauth_states", source)
        self.assertNotIn("authenticate(self.headers)", source)

    def test_final_dashboard_composition_exposes_customer_assets(self):
        source = (ROOT / "dashboard" / "server_part17.py").read_text(encoding="utf-8")
        for token in (
            "ensure_customer_discord_schema(legacy)",
            "install_customer_discord(legacy,_authenticate)",
            "install_customer_discord_oauth_callback(legacy)",
            '"/customer-integrations.html"',
            '"/customer-backups.html"',
            '"/customer-account.html"',
            '"/customer-core.js"',
        ):
            self.assertIn(token, source)

    def test_public_login_keeps_registration_and_recovery_links(self):
        html = (ROOT / "dashboard" / "web" / "customer-login.html").read_text(encoding="utf-8")
        self.assertIn('/customer-register.html', html)
        self.assertIn('/customer-forgot-password.html', html)


if __name__ == "__main__":
    unittest.main()
