#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"database"));sys.path.insert(0,str(ROOT/"dashboard"))

from customer_account_service import may_manage_members


class CustomerTeamC10C12Test(unittest.TestCase):
    def test_c10_owner_transfer_is_atomic_and_demotes_previous_owner(self):
        source=(ROOT/"database"/"customer_user_repository.py").read_text(encoding="utf-8")
        self.assertIn("def transfer_owner",source)
        self.assertIn("with self.backend.transaction()",source)
        self.assertIn("account_role='manager'",source)
        self.assertIn("account_role='owner'",source)
        self.assertIn("target owner must be active",source)

    def test_c11_account_lifecycle_preserves_membership_and_grants(self):
        source=(ROOT/"database"/"customer_user_repository.py").read_text(encoding="utf-8")
        self.assertIn("def set_active",source)
        self.assertIn("customer owner cannot be disabled",source)
        self.assertIn("def reset_password",source)
        self.assertNotIn("DELETE FROM instance_access",source)
        self.assertNotIn("DELETE FROM customer_account_members",source)

    def test_c12_activity_is_customer_scoped(self):
        source=(ROOT/"database"/"customer_user_repository.py").read_text(encoding="utf-8")
        self.assertIn("def list_activity",source)
        self.assertIn("SELECT username FROM customer_account_members WHERE customer_id",source)
        self.assertIn("SELECT id FROM instances WHERE customer_id",source)

    def test_api_exposes_lifecycle_without_accepting_customer_id(self):
        source=(ROOT/"dashboard"/"customer_team_api.py").read_text(encoding="utf-8")
        for path in [
            "/api/customer/team/activity",
            "/api/customer/team/members/status",
            "/api/customer/team/members/password",
            "/api/customer/team/owner/transfer",
        ]:
            self.assertIn(path,source)
        self.assertIn("require_customer(user)",source)
        self.assertNotIn('body.get("customer_id")',source)

    def test_only_owner_can_execute_team_lifecycle(self):
        self.assertTrue(may_manage_members("owner"))
        self.assertFalse(may_manage_members("manager"))
        self.assertFalse(may_manage_members("member"))
        source=(ROOT/"dashboard"/"customer_team_api.py").read_text(encoding="utf-8")
        self.assertIn("require_member_management(actor_role)",source)

    def test_ui_exposes_transfer_disable_password_and_audit(self):
        page=(ROOT/"dashboard"/"web"/"customer-members.html").read_text(encoding="utf-8")
        script=(ROOT/"dashboard"/"web"/"customer-members.js").read_text(encoding="utf-8")
        self.assertIn('id="customer-team-activity"',page)
        self.assertIn("/api/customer/team/owner/transfer",script)
        self.assertIn("/api/customer/team/members/status",script)
        self.assertIn("/api/customer/team/members/password",script)
        self.assertIn("/api/customer/team/activity",script)


if __name__=="__main__":unittest.main()
