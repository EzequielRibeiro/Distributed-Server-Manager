#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))
sys.path.insert(0, str(ROOT / "dashboard"))

from customer_account_service import may_manage_members
from customer_user_repository import CustomerUserRepository


class FakeCustomerUsers(CustomerUserRepository):
    def __init__(self):
        pass

    def list_members(self, customer_id):
        return [
            {"username": "owner", "account_role": "owner"},
            {"username": "member", "account_role": "member"},
        ]

    def list_instances(self, customer_id):
        return [{"id": f"{customer_id}-one", "name": "One", "game_id": "test"}]


class CustomerTeamC6C9Test(unittest.TestCase):
    def test_canonical_repository_protects_scope_helpers(self):
        repo = FakeCustomerUsers()
        self.assertEqual(1, repo.owner_count("alpha"))
        self.assertEqual("alpha-one", repo.require_instance("alpha", "alpha-one")["id"])
        with self.assertRaises(PermissionError):
            repo.require_instance("alpha", "beta-one")

    def test_only_owner_has_customer_member_management_permission(self):
        self.assertTrue(may_manage_members("owner"))
        self.assertFalse(may_manage_members("manager"))
        self.assertFalse(may_manage_members("member"))

    def test_team_api_scope_is_session_bound(self):
        source = (ROOT / "dashboard" / "customer_team_api.py").read_text(encoding="utf-8")
        self.assertIn("require_customer(user)", source)
        self.assertIn("require_instance(customer_id,instance_id)", source)
        self.assertIn("last customer owner cannot be removed", source)
        self.assertNotIn('body.get("customer_id")', source)

    def test_invitation_access_is_scope_checked(self):
        source = (ROOT / "dashboard" / "customer_invitation_api.py").read_text(encoding="utf-8")
        self.assertIn("users.require_instance(customer_id,str(instance_id))", source)
        self.assertNotIn('body.get("customer_id")', source)

    def test_http_composition_exposes_team_surface(self):
        source = (ROOT / "dashboard" / "server_part13.py").read_text(encoding="utf-8")
        self.assertIn("CUSTOMER_TEAM_PATHS", source)
        self.assertIn("TEAM_INVITATION_PATHS", source)
        self.assertIn("PUBLIC_INVITATION_PATHS", source)
        self.assertIn('"/customer-members.html"', source)
        self.assertIn("dispatch_customer_team", source)
        self.assertIn("dispatch_customer_invitations", source)

    def test_customer_ui_supports_create_invite_remove_and_access(self):
        page = (ROOT / "dashboard" / "web" / "customer-members.html").read_text(encoding="utf-8")
        script = (ROOT / "dashboard" / "web" / "customer-members.js").read_text(encoding="utf-8")
        self.assertIn('id="customer-member-form"', page)
        self.assertIn('id="customer-invite-form"', page)
        self.assertIn("/api/customer/team/members/create", script)
        self.assertIn("/api/customer/team/members/remove", script)
        self.assertIn("/api/customer/team/members/role", script)
        self.assertIn("/api/customer/team/access", script)
        self.assertIn("/api/customer/team/invitations/create", script)


if __name__ == "__main__":
    unittest.main()
