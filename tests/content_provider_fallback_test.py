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

    def test_auto_prefers_modrinth_and_stops_before_curseforge(self):
        calls=[]
        def search(user,iid,provider,ctype,query,limit):
            calls.append(provider)
            return [{"provider":"modrinth","name":"Example"}] if provider=="modrinth" else [{"provider":"curseforge"}]
        result=self.service(search).search_result({}, "i1", "auto", "mod", "example", 20)
        self.assertEqual(["modrinth"],calls)
        self.assertEqual("modrinth",result["provider_used"])
        self.assertFalse(result["fallback"]["upload_recommended"])

    def test_auto_falls_back_to_curseforge_when_modrinth_is_empty(self):
        calls=[]
        def search(user,iid,provider,ctype,query,limit):
            calls.append(provider)
            return [] if provider=="modrinth" else [{"provider":"curseforge","name":"Example"}]
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


if __name__=="__main__":
    unittest.main()
