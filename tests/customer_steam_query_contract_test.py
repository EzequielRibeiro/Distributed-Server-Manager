#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BACKEND=ROOT/"dashboard"/"customer_instance_connection_http.py"
FRONTEND=ROOT/"dashboard"/"web"/"customer-instance-connection.js"


class CustomerSteamQueryContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend=BACKEND.read_text(encoding="utf-8")
        cls.frontend=FRONTEND.read_text(encoding="utf-8")

    def test_valve_profiles_use_native_capirava_query(self):
        self.assertIn('native_steam = checker_type == "valve"',self.backend)
        self.assertIn('"provider": "capivara-steam-query" if native_steam else "ismygameserver.online"',self.backend)
        self.assertIn('payload["test_url"] = TEST_PATH',self.backend)

    def test_non_valve_profiles_keep_external_site(self):
        self.assertIn('https://ismygameserver.online/',self.backend)
        self.assertIn('else:',self.backend)

    def test_customer_ui_has_native_query_action(self):
        self.assertIn('id="customer-query-native"',self.frontend)
        self.assertIn('Testar Steam Query',self.frontend)
        self.assertIn('runNativeQuery',self.frontend)
        self.assertIn('/api/customer/instance/connection/test?instance_id=',self.frontend)
        self.assertIn('if(check.native)',self.frontend)
        self.assertIn('link.classList.add("hidden")',self.frontend)
        self.assertIn('link.classList.remove("hidden")',self.frontend)


if __name__=="__main__":
    unittest.main()
