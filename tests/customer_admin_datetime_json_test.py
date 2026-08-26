#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from customer_admin_api import dispatch_customer_admin_get


class CustomerAdminDatetimeJSONTest(unittest.TestCase):
    def test_detail_normalizes_database_datetimes_before_json_encoding(self):
        stamp = datetime(2026, 8, 25, 19, 41, 21, 137361, tzinfo=timezone.utc)
        detail = {
            "customer": {
                "customer_code": "CLI-000001",
                "created_at": stamp,
                "updated_at": stamp,
            },
            "users": [
                {
                    "username": "aurora",
                    "email_verified_at": stamp,
                    "must_change_password": False,
                }
            ],
            "contracts": [],
            "instances": [],
        }

        with patch("customer_admin_api.CustomerManagementRepository") as repository_type:
            repository_type.return_value.detail.return_value = detail
            status, payload = dispatch_customer_admin_get(
                "/api/admin/customer",
                {"customer_code": ["CLI-000001"]},
                user={
                    "username": "admin",
                    "role": "admin",
                    "scope_id": "controller-test",
                },
                backend=object(),
            )

        self.assertEqual(status, 200)
        encoded = json.dumps(payload)
        expected = "2026-08-25T19:41:21.137361+00:00"
        self.assertEqual(payload["customer"]["created_at"], expected)
        self.assertEqual(payload["customer"]["updated_at"], expected)
        self.assertEqual(payload["users"][0]["email_verified_at"], expected)
        self.assertIn(expected, encoded)


if __name__ == "__main__":
    unittest.main()
