#!/usr/bin/env python3
import unittest
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/"dashboard"))
from customer_instance_creation import _selector

class CustomerRuntimeBuildSelectorTest(unittest.TestCase):
    def runtime(self,resolver):
        return {"version":{"resolver":resolver},"variant":"fake","edition":"java"}

    def test_build_aware_resolvers_preserve_explicit_build(self):
        for resolver in ("papermc","forge_maven","neoforge_maven","purpur_api","sponge_maven","youer_api"):
            with self.subTest(resolver=resolver):
                self.assertEqual("1.21.1@42",_selector(self.runtime(resolver),"1.21.1","42"))

    def test_github_release_keeps_version_selector(self):
        self.assertEqual("1.21.1",_selector(self.runtime("github_releases"),"1.21.1","FeudalKings/1.0.1"))

    def test_fabric_translates_ui_build_to_resolver_selector(self):
        self.assertEqual("1.21.1@0.19.5@1.1.2",_selector(self.runtime("fabric_meta"),"1.21.1","loader-0.19.5_installer-1.1.2"))
        with self.assertRaisesRegex(ValueError,"invalid Fabric build selector"):
            _selector(self.runtime("fabric_meta"),"1.21.1","invalid")

    def test_version_only_resolvers_keep_version(self):
        for resolver in ("quilt_meta","minecraft_bedrock",""):
            with self.subTest(resolver=resolver):
                self.assertEqual("1.21.1",_selector(self.runtime(resolver),"1.21.1","ignored"))

if __name__ == '__main__': unittest.main()
