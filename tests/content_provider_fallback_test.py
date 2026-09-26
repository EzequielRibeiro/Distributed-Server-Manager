#!/usr/bin/env python3
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"dashboard",ROOT/"database",ROOT/"core"):
    if str(path) not in sys.path:sys.path.insert(0,str(path))

from customer_content_workspace import CustomerContentWorkspaceService


class ProviderFallbackTest(unittest.TestCase):
    def service(self, search_impl, providers=("modrinth","curseforge")):
        service=CustomerContentWorkspaceService.__new__(CustomerContentWorkspaceService)
        service.workspace=SimpleNamespace(root=ROOT)
        service._context_policy_details=lambda user,iid,permission:(
            {"id":iid,"game_id":"minecraft","runtime_id":"minecraft.java.fabric","game_version":"1.21.1"},
            {"providers":{"mod":list(providers),"modpack":list(providers),"plugin":["modrinth"]}},
            SimpleNamespace(),
        )
        service.search=search_impl
        return service

    def test_auto_combines_modrinth_and_curseforge(self):
        calls=[]
        def search(user,iid,provider,ctype,query,limit):
            calls.append(provider)
            return [{"content_id":"modrinth:abc","provider":"modrinth","name":"Example"}] if provider=="modrinth" else [{"content_id":"curseforge:42","provider":"curseforge","name":"Example"}]
        result=self.service(search).search_result({}, "i1", "auto", "mod", "example", 20)
        self.assertEqual(["modrinth","curseforge"],calls)
        self.assertEqual("multiple",result["provider_used"])
        self.assertEqual(2,result["count"])
        self.assertEqual({"modrinth","curseforge"},{x["provider"] for x in result["results"]})
        self.assertFalse(result["fallback"]["upload_recommended"])

    def test_auto_falls_back_to_curseforge_when_modrinth_is_empty(self):
        calls=[]
        def search(user,iid,provider,ctype,query,limit):
            calls.append(provider)
            return [] if provider=="modrinth" else [{"content_id":"curseforge:42","provider":"curseforge","name":"Example"}]
        result=self.service(search).search_result({}, "i1", "auto", "mod", "example", 20)
        self.assertEqual(["modrinth","curseforge"],calls)
        self.assertEqual("curseforge",result["provider_used"])

    def test_auto_recommends_upload_when_curseforge_is_unavailable(self):
        def search(user,iid,provider,ctype,query,limit):
            if provider=="modrinth":return []
            raise ValueError("CurseForge não autorizado: verifique a API key no Controller.")
        result=self.service(search).search_result({}, "i1", "auto", "modpack", "pack", 20)
        self.assertEqual([],result["results"])
        self.assertTrue(result["fallback"]["upload_recommended"])
        self.assertEqual("unavailable",result["fallback"]["attempts"][-1]["status"])

    def test_auto_uses_only_declared_runtime_providers(self):
        calls=[]
        def search(user,iid,provider,ctype,query,limit):
            calls.append(provider);return []
        result=self.service(search,providers=("modrinth",)).search_result({}, "i1", "auto", "mod", "x", 20)
        self.assertEqual(["modrinth"],calls)
        self.assertTrue(result["fallback"]["upload_recommended"])


    def test_modpack_exact_prefix_from_curseforge_outranks_loose_modrinth_hit(self):
        calls=[]
        def search(user,iid,provider,ctype,query,limit):
            calls.append(provider)
            if provider=="modrinth":
                return [{"content_id":"modrinth:near","provider":"modrinth",
                         "name":"All the MrCrayfish's Mods [NEOFORGE]","downloads":1800}]
            return [{"content_id":"curseforge:1148445","provider":"curseforge",
                     "name":"All the Mods 11 - ATM11","downloads":900000}]
        result=self.service(search).search_result({},"i1","auto","modpack","All the mods",20)
        self.assertEqual(["modrinth","curseforge"],calls)
        self.assertEqual("curseforge:1148445",result["results"][0]["content_id"])
        self.assertEqual("multiple",result["provider_used"])
        self.assertEqual(["success","success"],[x["status"] for x in result["fallback"]["attempts"]])

    def test_missing_curseforge_key_is_reported_even_with_modrinth_results(self):
        def search(user,iid,provider,ctype,query,limit):
            if provider=="curseforge":
                raise ValueError("CurseForge API key file is unavailable")
            return [{"content_id":"modrinth:near","provider":"modrinth","name":"Near match"}]
        result=self.service(search).search_result({},"i1","auto","modpack","pack",20)
        self.assertEqual("modrinth",result["provider_used"])
        self.assertEqual(1,result["count"])
        self.assertTrue(result["fallback"]["degraded"])
        self.assertEqual("unavailable",result["fallback"]["attempts"][1]["status"])
        self.assertFalse(result["fallback"]["upload_recommended"])

    def test_merge_removes_duplicate_ids_and_honors_limit(self):
        def search(user,iid,provider,ctype,query,limit):
            if provider=="modrinth":
                return [{"content_id":"modrinth:a","name":"A","provider":"modrinth","downloads":1}] * 3
            return [{"content_id":"curseforge:b","name":"B","provider":"curseforge","downloads":2}]
        result=self.service(search).search_result({},"i1","auto","modpack","z",1)
        self.assertEqual(1,result["count"])
        self.assertEqual(1,len(result["results"]))
        self.assertEqual(2,len(result["fallback"]["attempts"]))

if __name__=="__main__":
    unittest.main()
