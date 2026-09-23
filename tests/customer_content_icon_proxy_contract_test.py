#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTTP = ROOT / "dashboard" / "customer_content_http.py"


class CustomerContentIconProxyContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = HTTP.read_text(encoding="utf-8")

    def test_icon_proxy_is_same_origin_and_authenticated(self):
        text = self.text
        self.assertIn('ICON=PATH+"/icon"', text)
        self.assertIn('if parsed.path==ICON:', text)
        self.assertIn('user=require_user(self)', text)
        self.assertIn('api.workspace.require(user,instance_id,"content.read")', text)

    def test_icon_proxy_only_allows_known_https_cdn_hosts(self):
        text = self.text
        self.assertIn('ICON_HOST_SUFFIXES=(".modrinth.com",".forgecdn.net")', text)
        self.assertIn('parsed.scheme!="https"', text)
        self.assertIn('content icon source is not allowed', text)
        self.assertIn('content icon redirect is not allowed', text)

    def test_icon_proxy_limits_type_and_size(self):
        text = self.text
        self.assertIn('ICON_MAX_BYTES=4*1024*1024', text)
        self.assertIn('"image/avif"', text)
        self.assertIn('"image/webp"', text)
        self.assertIn('"image/png"', text)
        self.assertIn('"image/jpeg"', text)
        self.assertIn('"image/gif"', text)
        self.assertIn('content icon exceeds size limit', text)
        self.assertIn('X-Content-Type-Options","nosniff"', text)


if __name__ == "__main__":
    unittest.main()
