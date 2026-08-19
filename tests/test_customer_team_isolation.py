#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from customer_team_repository import CustomerTeamRepository


class TinySQLiteBackend:
    name = "sqlite"

    def __init__(self, path: Path):
        self.path = path

    def initialize(self):
        return {"ok": True}

    def _open(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def connect(self):
        connection = self._open()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self):
        connection = self._open()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def backend_with_team_schema(tmp_path: Path):
    backend = TinySQLiteBackend(tmp_path / "team.db")
    with backend.transaction() as connection:
        connection.executescript("""
            CREATE TABLE dashboard_users(username TEXT PRIMARY KEY, role TEXT NOT NULL, scope_id TEXT, active INTEGER NOT NULL, password_hash TEXT DEFAULT 'x');
            CREATE TABLE customer_account_members(customer_id TEXT NOT NULL, username TEXT NOT NULL, account_role TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(customer_id,username));
            CREATE TABLE instances(id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, name TEXT NOT NULL, game_id TEXT NOT NULL, status TEXT NOT NULL);
            CREATE TABLE instance_access(username TEXT NOT NULL, instance_id TEXT NOT NULL, permission_profile TEXT NOT NULL, PRIMARY KEY(username,instance_id));
        """)
        connection.executemany("INSERT INTO dashboard_users(username,role,scope_id,active) VALUES (?,?,?,1)", [
            ("alice", "customer", "customer-a"),
            ("bob", "customer", "customer-a"),
            ("mallory", "customer", "customer-b"),
        ])
        connection.executemany("INSERT INTO customer_account_members(customer_id,username,account_role) VALUES (?,?,?)", [
            ("customer-a", "alice", "owner"),
            ("customer-a", "bob", "member"),
            ("customer-b", "mallory", "owner"),
        ])
        connection.executemany("INSERT INTO instances(id,customer_id,name,game_id,status) VALUES (?,?,?,?,?)", [
            ("a-1", "customer-a", "A1", "dayz", "offline"),
            ("b-1", "customer-b", "B1", "dayz", "offline"),
        ])
    return backend


def test_customer_cannot_delegate_access_to_other_customer_instance(tmp_path):
    repo = CustomerTeamRepository(backend_with_team_schema(tmp_path))
    with pytest.raises(PermissionError):
        repo.set_instance_access("customer-a", "bob", "b-1", "viewer")


def test_cross_customer_user_never_resolves_permission_profile(tmp_path):
    backend = backend_with_team_schema(tmp_path)
    with backend.transaction() as connection:
        connection.execute("INSERT INTO instance_access(username,instance_id,permission_profile) VALUES ('mallory','a-1','manager')")
    repo = CustomerTeamRepository(backend)
    assert repo.permission_profile("customer-a", "mallory", "a-1") is None


def test_owner_cannot_be_removed_by_team_repository(tmp_path):
    repo = CustomerTeamRepository(backend_with_team_schema(tmp_path))
    with pytest.raises(PermissionError):
        repo.remove_member("customer-a", "alice")
