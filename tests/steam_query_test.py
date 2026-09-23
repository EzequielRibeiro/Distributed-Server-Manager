#!/usr/bin/env python3
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT/"dashboard") not in sys.path:sys.path.insert(0,str(ROOT/"dashboard"))

from steam_query import _parse_info,_parse_rules


class SteamQueryParserTest(unittest.TestCase):
    def test_parses_a2s_info(self):
        payload=(
            b"\xff\xff\xff\xffI"
            +bytes([17])
            +b"Capivara DSM\x00chernarusplus\x00dayz\x00Server Test\x00"
            +struct.pack("<H",221100)
            +bytes([0,64,0])
            +b"d"
            +b"l"
            +bytes([0,1])
            +b"1.29.163709\x00"
        )
        info=_parse_info(payload)
        self.assertEqual(info["name"],"Capivara DSM")
        self.assertEqual(info["map"],"chernarusplus")
        self.assertEqual(info["folder"],"dayz")
        self.assertEqual(info["players"],0)
        self.assertEqual(info["max_players"],64)
        self.assertEqual(info["version"],"1.29.163709")

    def test_parses_standard_a2s_rules(self):
        payload=b"\xff\xff\xff\xffE"+struct.pack("<H",2)+b"hostname\x00Capivara DSM\x00clientPort\x0024002\x00"
        rules=_parse_rules(payload)
        self.assertEqual(rules["format"],"key_value")
        self.assertEqual(rules["rules"]["hostname"],"Capivara DSM")
        self.assertEqual(rules["rules"]["clientPort"],"24002")

    def test_keeps_printable_strings_for_dayz_binary_rules(self):
        payload=b"\xff\xff\xff\xffE"+struct.pack("<H",10)+b"\x01\x02VPPAdminTools\x1b\x18CodeLock\xc1Community Framework\x04dayz\x00clientPort\x0024002\x00"
        rules=_parse_rules(payload)
        self.assertEqual(rules["format"],"binary")
        self.assertIn("VPPAdminTools",rules["strings"])
        self.assertIn("CodeLock",rules["strings"])
        self.assertIn("Community Framework",rules["strings"])


if __name__=="__main__":
    unittest.main()
