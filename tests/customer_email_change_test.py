#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "core"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from admin_management_repository import AdminManagementRepository
from customer_email_change_service import CustomerEmailChangeService
from runtime_backend import backend_from_environment


class CaptureTransport:
    def __init__(self):
        self.deliveries = []
    def send_verification(self, *, destination, token, expires_minutes):
        self.deliveries.append({"destination": destination, "token": token, "expires_minutes": expires_minutes})


class CustomerEmailChangeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = backend_from_environment({
            "DSM_DATABASE_DRIVER": "sqlite",
            "DSM_DATABASE": str(Path(self.temp.name) / "capivara.db"),
        })
        self.backend.initialize()
        self.admin = AdminManagementRepository(self.backend)
        with self.admin.session(transaction=True) as session:
            session.execute("INSERT INTO nodes(id,name,role,status) VALUES (?,?,?,?)", ("controller-node", "Controller", "controller", "active"))
            session.execute("INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)", ("controller-1", "controller-node", "Controller", "active"))
        self.customer = self.admin.create_customer(name="Owner Customer", username="owner", password_hash="hash", controller_id="controller-1", email="old@example.test")
        with self.admin.session(transaction=True) as session:
            session.execute("UPDATE customers SET account_email=?,email_verified_at=CURRENT_TIMESTAMP WHERE id=?", ("old@example.test", self.customer["id"]))
            session.execute("INSERT INTO customer_account_members(customer_id,username,account_role) VALUES (?,?,?)", (self.customer["id"], "owner", "owner"))
            session.execute("INSERT INTO customer_user_identities(username,email,email_verified_at) VALUES (?,?,CURRENT_TIMESTAMP)", ("owner", "old@example.test"))
        self.user = {"role": "customer", "scope_id": self.customer["customer_code"], "username": "owner"}
        self.transport = CaptureTransport()
        self.service = CustomerEmailChangeService(self.backend, transport=self.transport, max_requests=20)

    def tearDown(self):
        self.temp.cleanup()

    def _request_json(self, challenge_id):
        with self.admin.session() as session:
            row = session.execute("SELECT request_json,status FROM operations WHERE id=?", (challenge_id,)).fetchone()
        return str(row["request_json"]), str(row["status"])

    def test_token_is_only_delivered_cleartext_and_persisted_as_hash(self):
        result = self.service.initiate(user=self.user, target_email="new@example.test", confirmed=True, correlation_id="corr-1")
        self.assertTrue(result["accepted"])
        self.assertNotIn("token", result)
        token = self.transport.deliveries[-1]["token"]
        raw, status = self._request_json(result["challenge_id"])
        self.assertEqual(status, "pending")
        self.assertNotIn(token, raw)
        payload = json.loads(raw)
        self.assertIn("token_hash", payload)
        self.assertNotEqual(payload["token_hash"], token)

    def test_successful_verification_is_single_use_and_updates_identity(self):
        challenge = self.service.initiate(user=self.user, target_email="new@example.test", confirmed=True)
        token = self.transport.deliveries[-1]["token"]
        result = self.service.verify(user=self.user, challenge_id=challenge["challenge_id"], token=token, confirmed=True)
        self.assertTrue(result["changed"])
        with self.admin.session() as session:
            identity = session.execute("SELECT email FROM customer_user_identities WHERE username='owner'").fetchone()
            customer = session.execute("SELECT account_email FROM customers WHERE id=?", (self.customer["id"],)).fetchone()
        self.assertEqual(identity["email"], "new@example.test")
        self.assertEqual(customer["account_email"], "new@example.test")
        with self.assertRaises(ValueError):
            self.service.verify(user=self.user, challenge_id=challenge["challenge_id"], token=token, confirmed=True)

    def test_newer_challenge_supersedes_previous_token(self):
        first = self.service.initiate(user=self.user, target_email="first@example.test", confirmed=True)
        first_token = self.transport.deliveries[-1]["token"]
        second = self.service.initiate(user=self.user, target_email="second@example.test", confirmed=True)
        _, first_status = self._request_json(first["challenge_id"])
        self.assertEqual(first_status, "superseded")
        with self.assertRaises(ValueError):
            self.service.verify(user=self.user, challenge_id=first["challenge_id"], token=first_token, confirmed=True)
        second_token = self.transport.deliveries[-1]["token"]
        self.assertTrue(self.service.verify(user=self.user, challenge_id=second["challenge_id"], token=second_token, confirmed=True)["changed"])

    def test_member_and_wrong_tenant_cannot_change_owner_email(self):
        with self.admin.session(transaction=True) as session:
            session.execute("INSERT INTO dashboard_users(username,password_hash,role,customer_id,active) VALUES (?,?,?,?,1)", ("member", "hash", "customer", self.customer["id"]))
            session.execute("INSERT INTO customer_account_members(customer_id,username,account_role) VALUES (?,?,?)", (self.customer["id"], "member", "member"))
            session.execute("INSERT INTO customer_user_identities(username,email,email_verified_at) VALUES (?,?,CURRENT_TIMESTAMP)", ("member", "member@example.test"))
        member = {"role": "customer", "scope_id": self.customer["customer_code"], "username": "member"}
        with self.assertRaises(PermissionError):
            self.service.initiate(user=member, target_email="member-new@example.test", confirmed=True)
        wrong = {"role": "customer", "scope_id": "CLI-999999", "username": "owner"}
        with self.assertRaises(PermissionError):
            self.service.initiate(user=wrong, target_email="wrong@example.test", confirmed=True)

    def test_duplicate_email_is_rejected_without_delivery(self):
        other = self.admin.create_customer(name="Other", username="other", password_hash="hash", controller_id="controller-1", email="taken@example.test")
        with self.admin.session(transaction=True) as session:
            session.execute("INSERT INTO customer_account_members(customer_id,username,account_role) VALUES (?,?,?)", (other["id"], "other", "owner"))
            session.execute("INSERT INTO customer_user_identities(username,email,email_verified_at) VALUES (?,?,CURRENT_TIMESTAMP)", ("other", "taken@example.test"))
        with self.assertRaisesRegex(ValueError, "email_unavailable"):
            self.service.initiate(user=self.user, target_email="taken@example.test", confirmed=True)
        self.assertEqual(self.transport.deliveries, [])

    def test_expired_challenge_is_rejected(self):
        challenge = self.service.initiate(user=self.user, target_email="expire@example.test", confirmed=True)
        token = self.transport.deliveries[-1]["token"]
        with self.admin.session(transaction=True) as session:
            row = session.execute("SELECT request_json FROM operations WHERE id=?", (challenge["challenge_id"],)).fetchone()
            payload = json.loads(row["request_json"])
            payload["expires_at"] = "2000-01-01T00:00:00Z"
            session.execute("UPDATE operations SET request_json=? WHERE id=?", (json.dumps(payload, separators=(",", ":")), challenge["challenge_id"]))
        with self.assertRaisesRegex(ValueError, "invalid_or_expired_challenge"):
            self.service.verify(user=self.user, challenge_id=challenge["challenge_id"], token=token, confirmed=True)

    def test_explicit_confirmation_and_ui_contract(self):
        with self.assertRaisesRegex(ValueError, "explicit_confirmation_required"):
            self.service.initiate(user=self.user, target_email="new@example.test", confirmed=False)
        js = (ROOT / "dashboard" / "web" / "customer-email-change.js").read_text(encoding="utf-8")
        profile = (ROOT / "dashboard" / "web" / "customer-profile.js").read_text(encoding="utf-8")
        self.assertIn("/api/customer/email-change/initiate", js)
        self.assertIn("/api/customer/email-change/verify", js)
        self.assertIn("data-customer-email-change", profile)
        self.assertNotIn("token_hash", js)


if __name__ == "__main__":
    unittest.main()
