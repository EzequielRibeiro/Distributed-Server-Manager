#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import customer_profile_self_service_http as profile_http

CUSTOMER = {"id":42,"customer_code":"CLI-000042","name":"Cliente","legal_name":"Cliente Ltda","phone":"+55 19 99999-0000","document_type":"cnpj","document_number":"123","account_email":"owner@example.test","email_verified_at":"2026-08-01T00:00:00Z","registration_status":"active","controller_id":"controller-a","billing_provider":"secret-provider","billing_customer_id":"secret-billing-id"}

class CustomerSelfServiceProfileTest(unittest.TestCase):
    def setUp(self):
        self.backend=object(); self.user={"role":"customer","scope_id":"CLI-000042","username":"owner"}
    def test_get_returns_only_customer_safe_profile(self):
        with patch.object(profile_http,"_identity",return_value=(42,dict(CUSTOMER),"owner","owner")):
            status,payload=profile_http.customer_profile_get(user=self.user,backend=self.backend)
        self.assertEqual(status,200); self.assertTrue(payload["editable"]); profile=payload["profile"]
        self.assertEqual(profile["customer_code"],"CLI-000042"); self.assertEqual(profile["account_email"],"owner@example.test")
        for field in ("controller_id","billing_provider","billing_customer_id"): self.assertNotIn(field,profile)
    def test_member_can_read_but_cannot_edit(self):
        with patch.object(profile_http,"_identity",return_value=(42,dict(CUSTOMER),"member","member")):
            status,payload=profile_http.customer_profile_get(user=self.user,backend=self.backend)
            self.assertEqual(status,200); self.assertFalse(payload["editable"]); self.assertEqual(payload["profile"]["account_role"],"member")
            status,payload=profile_http.customer_profile_update({"changes":{"phone":"1"}},user=self.user,backend=self.backend)
        self.assertEqual(status,403); self.assertEqual(payload["error"],"forbidden")
    def test_protected_identity_and_admin_fields_are_rejected_before_write(self):
        for field in ("account_email","customer_code","controller_id","registration_status","billing_status","username"):
            status,payload=profile_http.customer_profile_update({"changes":{field:"changed"}},user=self.user,backend=self.backend)
            self.assertEqual(status,400,field); self.assertEqual(payload["error"],"protected_fields",field)
    def test_owner_update_reuses_admin_validation_but_only_safe_fields(self):
        result={"updated":True,"changed_fields":["name","phone"],"before":{"name":"Cliente","phone":"+55"},"after":{"name":"Novo Nome","phone":"+5519"},"customer":dict(CUSTOMER,name="Novo Nome",phone="+5519")}
        repo=Mock(); repo.update.return_value=result; event_repo=Mock()
        with patch.object(profile_http,"_identity",return_value=(42,dict(CUSTOMER),"owner","owner")), patch.object(profile_http,"CustomerProfileAdminRepository",return_value=repo), patch.object(profile_http,"audit_customer_event") as audit, patch.object(profile_http,"UniversalEventRepository",return_value=event_repo):
            status,payload=profile_http.customer_profile_update({"changes":{"name":"Novo Nome","phone":"+5519"},"correlation_id":"corr-1"},user=self.user,backend=self.backend)
        self.assertEqual(status,200); repo.update.assert_called_once_with(42,{"name":"Novo Nome","phone":"+5519"}); self.assertEqual(payload["correlation_id"],"corr-1"); self.assertNotIn("controller_id",payload["profile"]); audit.assert_called_once()
        event=event_repo.publish.call_args.args[0]; self.assertEqual(event["event_type"],"CUSTOMER_PROFILE_UPDATED"); self.assertEqual(event["correlation_id"],"corr-1"); self.assertEqual(event["data"]["changed_fields"],["name","phone"]); self.assertNotIn("before",event["data"]); self.assertNotIn("after",event["data"])
    def test_ui_keeps_email_read_only_and_uses_customer_cookie_session(self):
        script=(ROOT/"dashboard"/"web"/"customer-profile.js").read_text(encoding="utf-8"); html=(ROOT/"dashboard"/"web"/"customer.html").read_text(encoding="utf-8")
        for marker in ('/api/customer/profile','E-mail da conta','Somente leitura','X-Capivara-Auth-Area','credentials:"same-origin"','/customer-login.html','customer-profile-role','emailChange.hidden=!editable'): self.assertIn(marker,script)
        self.assertNotIn('account_email:',script); self.assertNotIn('sessionStorage',script); self.assertNotIn('Authorization',script); self.assertIn('data-customer-profile',html); self.assertIn('/customer-profile.js',html)

if __name__=="__main__": unittest.main()
