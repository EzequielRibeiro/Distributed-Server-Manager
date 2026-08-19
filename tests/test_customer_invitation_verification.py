#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,sys
from contextlib import contextmanager
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"database")); sys.path.insert(0,str(ROOT/"dashboard"))
from customer_invitation_repository import CustomerInvitationRepository
from customer_verification_repository import CustomerVerificationRepository
from customer_audit import audit_customer_event
class TinySQLiteBackend:
    name="sqlite"
    def __init__(self,path:Path):self.path=path
    def initialize(self):return {"ok":True}
    def _open(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;c.execute("PRAGMA foreign_keys=ON");return c
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
def build_backend(tmp_path:Path):
    b=TinySQLiteBackend(tmp_path/"customer-flow.db")
    with b.transaction() as c:
        c.executescript("""
        CREATE TABLE customers(id TEXT PRIMARY KEY,status TEXT DEFAULT 'active',registration_status TEXT,email_verified_at TEXT,updated_at TEXT);
        CREATE TABLE dashboard_users(username TEXT PRIMARY KEY,password_hash TEXT,role TEXT,scope_id TEXT,active INTEGER,updated_at TEXT);
        CREATE TABLE customer_account_members(customer_id TEXT,username TEXT,account_role TEXT,PRIMARY KEY(customer_id,username));
        CREATE TABLE instances(id TEXT PRIMARY KEY,customer_id TEXT,name TEXT,game_id TEXT,status TEXT);
        CREATE TABLE instance_access(username TEXT,instance_id TEXT,permission_profile TEXT,PRIMARY KEY(username,instance_id));
        CREATE TABLE customer_user_identities(username TEXT PRIMARY KEY,email TEXT NOT NULL,email_verified_at TEXT);
        CREATE UNIQUE INDEX ix_identity_email ON customer_user_identities(LOWER(email));
        CREATE TABLE customer_invitations(id TEXT PRIMARY KEY,customer_id TEXT,email TEXT,account_role TEXT,token_hash TEXT UNIQUE,expires_at TEXT,accepted_at TEXT,revoked_at TEXT,invited_by TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE customer_invitation_access(invitation_id TEXT,instance_id TEXT,permission_profile TEXT,PRIMARY KEY(invitation_id,instance_id));
        CREATE TABLE customer_email_verification(id TEXT PRIMARY KEY,username TEXT,token_hash TEXT UNIQUE,expires_at TEXT,consumed_at TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL,instance_id TEXT,action TEXT,result TEXT,details TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        c.executemany("INSERT INTO customers(id,status,registration_status,updated_at) VALUES (?, 'active', 'active', CURRENT_TIMESTAMP)",[("customer-a",),("customer-b",)])
        c.executemany("INSERT INTO dashboard_users(username,password_hash,role,scope_id,active,updated_at) VALUES (?,?, 'customer',?,1,CURRENT_TIMESTAMP)",[("alice","x","customer-a"),("mallory","x","customer-b")])
        c.executemany("INSERT INTO customer_account_members(customer_id,username,account_role) VALUES (?,?, 'owner')",[("customer-a","alice"),("customer-b","mallory")])
        c.executemany("INSERT INTO customer_user_identities(username,email,email_verified_at) VALUES (?,?,CURRENT_TIMESTAMP)",[("alice","alice@example.test"),("mallory","mallory@example.test")])
        c.executemany("INSERT INTO instances(id,customer_id,name,game_id,status) VALUES (?,?,?,?, 'offline')",[("a-1","customer-a","A1","dayz"),("b-1","customer-b","B1","dayz")])
    return b
def test_invitation_is_scoped_hashed_and_one_use(tmp_path):
    b=build_backend(tmp_path);repo=CustomerInvitationRepository(b)
    with pytest.raises(PermissionError):repo.create("customer-a","new@example.test","member",{"b-1":"viewer"},"alice")
    created=repo.create("customer-a","new@example.test","member",{"a-1":"operator"},"alice")
    with b.connect() as c:
        stored=c.execute("SELECT token_hash FROM customer_invitations WHERE id=?",(created["id"],)).fetchone()[0];assert created["token"] not in stored and len(stored)==64
    accepted=repo.accept(created["token"],"hashed-password");assert accepted["customer_id"]=="customer-a"
    with b.connect() as c:
        assert c.execute("SELECT scope_id FROM dashboard_users WHERE username=?",(accepted["username"],)).fetchone()[0]=="customer-a"
        assert c.execute("SELECT permission_profile FROM instance_access WHERE username=? AND instance_id='a-1'",(accepted["username"],)).fetchone()[0]=="operator"
        identity=c.execute("SELECT email,email_verified_at FROM customer_user_identities WHERE username=?",(accepted["username"],)).fetchone();assert identity[0]=="new@example.test" and identity[1]
    with pytest.raises(ValueError):repo.accept(created["token"],"other")
def test_verification_activates_pending_account_and_is_one_use(tmp_path):
    b=build_backend(tmp_path)
    with b.transaction() as c:
        c.execute("INSERT INTO customers(id,status,registration_status,updated_at) VALUES ('pending-c','active','pending',CURRENT_TIMESTAMP)")
        c.execute("INSERT INTO dashboard_users(username,password_hash,role,scope_id,active,updated_at) VALUES ('pending','x','customer','pending-c',0,CURRENT_TIMESTAMP)")
        c.execute("INSERT INTO customer_user_identities(username,email) VALUES ('pending','pending@example.test')")
    repo=CustomerVerificationRepository(b);token=repo.create("pending");result=repo.consume(token);assert result["customer_id"]=="pending-c"
    with b.connect() as c:
        assert c.execute("SELECT active FROM dashboard_users WHERE username='pending'").fetchone()[0]==1
        row=c.execute("SELECT registration_status,email_verified_at FROM customers WHERE id='pending-c'").fetchone();assert row[0]=="active" and row[1]
    with pytest.raises(ValueError):repo.consume(token)
def test_customer_audit_records_event(tmp_path):
    b=build_backend(tmp_path);audit_customer_event(b,username="alice",action="customer.invitation_created",details={"customer_id":"customer-a"})
    with b.connect() as c:
        row=c.execute("SELECT action,result,details FROM audit_log WHERE username='alice'").fetchone();assert row[0]=="customer.invitation_created" and row[1]=="success" and "customer-a" in row[2]
