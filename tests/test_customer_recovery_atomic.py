#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,sys
from contextlib import contextmanager
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"database"))
from customer_account_repository import CustomerAccountRepository
class TinySQLiteBackend:
    name="sqlite"
    def __init__(self,path):self.path=path
    def initialize(self):return {"ok":True}
    def _open(self):c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
    @contextmanager
    def connect(self):
        c=self._open()
        try:yield c
        finally:c.close()
    @contextmanager
    def transaction(self):
        c=self._open();c.execute("BEGIN IMMEDIATE")
        try:yield c;c.commit()
        except Exception:c.rollback();raise
        finally:c.close()
def test_password_update_and_token_consumption_are_atomic(tmp_path):
    b=TinySQLiteBackend(tmp_path/"recovery.db")
    with b.transaction() as c:
        c.executescript("CREATE TABLE dashboard_users(username TEXT PRIMARY KEY,password_hash TEXT,role TEXT,active INTEGER,updated_at TEXT); CREATE TABLE customer_password_recovery(id TEXT PRIMARY KEY,username TEXT,token_hash TEXT UNIQUE,expires_at TEXT,consumed_at TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);")
        c.execute("INSERT INTO dashboard_users VALUES ('alice','old','customer',1,CURRENT_TIMESTAMP)")
    repo=CustomerAccountRepository(b);token=repo.create_recovery("alice");username=repo.reset_password(token,"new-hash");assert username=="alice"
    with b.connect() as c:
        assert c.execute("SELECT password_hash FROM dashboard_users WHERE username='alice'").fetchone()[0]=="new-hash"
        assert c.execute("SELECT consumed_at FROM customer_password_recovery").fetchone()[0]
