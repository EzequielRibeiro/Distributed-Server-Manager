#!/usr/bin/env python3
from __future__ import annotations

import unittest

from database.backends.baseline_postgresql_backend import _json_text_loads


class PostgreSQLJSONBoundaryTest(unittest.TestCase):
    def test_bytes_are_returned_as_json_text(self):
        self.assertEqual(
            _json_text_loads(b'{"resource_profile_id":"standard"}'),
            '{"resource_profile_id":"standard"}',
        )

    def test_memoryview_is_returned_as_json_text(self):
        self.assertEqual(
            _json_text_loads(memoryview(b'{"enabled":true}')),
            '{"enabled":true}',
        )

    def test_existing_text_is_preserved(self):
        value = '{"customer_code":"CLI-000001"}'
        self.assertIs(_json_text_loads(value), value)


if __name__ == "__main__":
    unittest.main()
