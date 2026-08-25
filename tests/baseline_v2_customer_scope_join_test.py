#!/usr/bin/env python3
from __future__ import annotations
import unittest

from database.baseline_v2_compiler import _rewrite_legacy_customer_scope_joins


class BaselineV2CustomerScopeJoinTest(unittest.TestCase):
    def test_customer_backfill_uses_numeric_customer_id(self):
        source = """
SELECT c.id, u.username
FROM dashboard_users u
JOIN customers c
    ON c.id = u.scope_id
WHERE u.role = 'customer';
"""
        compiled = _rewrite_legacy_customer_scope_joins(source)
        self.assertIn("ON c.id = u.customer_id", compiled)
        self.assertNotIn("ON c.id = u.scope_id", compiled)

    def test_non_customer_scope_usage_is_preserved(self):
        source = "SELECT scope_id FROM dashboard_users WHERE scope_id IS NOT NULL;"
        self.assertEqual(_rewrite_legacy_customer_scope_joins(source), source)


if __name__ == "__main__":
    unittest.main()
