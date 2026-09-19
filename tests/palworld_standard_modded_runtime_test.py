#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from core.agent_eligibility import evaluate_agent_eligibility
from core.placement_requirements import requirements_from_runtime_definition


def _load(path:Path,name:str):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class PalworldStandardModdedRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime_root=ROOT/"catalog"/"v2"/"games"/"palworld"/"runtimes"
        cls.standard=json.loads((runtime_root/"stable.json").read_text(encoding="utf-8"))
        cls.modded=json.loads((runtime_root/"windows-modded.json").read_text(encoding="utf-8"))

    def _agent(self,os_name,profiles):
        return {
            "status":"active","health_status":"online",
            "capabilities":{
                "platform":{"os":os_name,"architecture":"x86_64"},
                "runtime_profiles":profiles,
                "native-linux":os_name=="linux",
                "native-windows":os_name=="windows",
                "steamcmd":True,
            },
        }

    def test_standard_can_place_on_linux_or_windows(self):
        req=requirements_from_runtime_definition(self.standard)
        self.assertEqual(req.operating_systems,frozenset({"linux","windows"}))
        for os_name in ("linux","windows"):
            result=evaluate_agent_eligibility(
                runtime=self._agent(os_name,["palworld","palworld.stable"]),
                port_summary={"ranges":[]},
                requirements=req,
            )
            self.assertTrue(result.eligible,(os_name,result.reasons))

    def test_modded_requires_windows_profile(self):
        req=requirements_from_runtime_definition(self.modded)
        self.assertEqual(req.operating_systems,frozenset({"windows"}))
        windows=evaluate_agent_eligibility(
            runtime=self._agent("windows",["palworld","palworld.stable","palworld.windows-modded"]),
            port_summary={"ranges":[]},requirements=req,
        )
        linux=evaluate_agent_eligibility(
            runtime=self._agent("linux",["palworld","palworld.stable"]),
            port_summary={"ranges":[]},requirements=req,
        )
        self.assertTrue(windows.eligible,windows.reasons)
        self.assertFalse(linux.eligible)
        self.assertTrue(any(reason.startswith("unsupported_os") or reason=="unsupported_runtime_profile" for reason in linux.reasons))

    def test_modded_catalog_exposes_only_workshop_content(self):
        content=self.modded["content"]
        self.assertEqual(content["steam_workshop"]["app_id"],"1623730")
        self.assertEqual(content["steam_workshop"]["auth"],"required")
        self.assertEqual(content["managed"]["types"]["workshop"]["providers"],["steam-workshop"])
        self.assertEqual(content["activation"]["adapter"],"palworld")
        self.assertEqual(self.modded["requirements"]["os"],["windows"])

    def test_windows_registry_claims_both_palworld_runtimes(self):
        registry=(ROOT/"agents"/"windows"/"runtime"/"profiles"/"registry.py").read_text(encoding="utf-8")
        profile=(ROOT/"agents"/"windows"/"runtime"/"profiles"/"palworld.py").read_text(encoding="utf-8")
        self.assertIn("PalworldRuntimeProfile",registry)
        self.assertIn('"palworld.stable"',profile)
        self.assertIn('"palworld.windows-modded"',profile)

    def test_workshop_activation_validates_server_mod_and_materializes_settings(self):
        module=_load(
            ROOT/"agents"/"windows"/"runtime"/"content_activation_palworld.py",
            f"palworld_activation_{id(self)}",
        )
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            runtime=root/"runtime";runtime.mkdir()
            workshop=root/"content"/"workshop";item=workshop/"123456";item.mkdir(parents=True)
            (item/"Info.json").write_text(json.dumps({
                "PackageName":"ExampleServerMod",
                "InstallRules":[{"IsServer":True}],
            }),encoding="utf-8")
            projected=module.project_palworld_activation(
                {"environment_id":"palworld.windows-modded"},
                [{
                    "content_type":"workshop",
                    "managed_path":str(item),
                    "activation":{"adapter":"palworld","mode":"server-mod"},
                }],
            )
            self.assertEqual(projected["packages"],["ExampleServerMod"])
            self.assertEqual(Path(projected["workshop_root"]),workshop.resolve())
            spec={
                "environment_id":"palworld.windows-modded",
                "working_directory":str(runtime),
                "content_palworld_packages":projected["packages"],
                "content_palworld_workshop_root":projected["workshop_root"],
            }
            self.assertEqual(module.materialize_palworld_settings(spec),["Mods/PalModSettings.ini"])
            text=(runtime/"Mods"/"PalModSettings.ini").read_text(encoding="utf-8")
            self.assertIn("bGlobalEnableMod=true",text)
            self.assertIn("ActiveModList=ExampleServerMod",text)
            self.assertIn("WorkshopRootDir=",text)

    def test_non_server_workshop_item_fails_closed(self):
        module=_load(
            ROOT/"agents"/"windows"/"runtime"/"content_activation_palworld.py",
            f"palworld_activation_invalid_{id(self)}",
        )
        with tempfile.TemporaryDirectory() as td:
            item=Path(td)/"workshop"/"123";item.mkdir(parents=True)
            (item/"Info.json").write_text(json.dumps({
                "PackageName":"ClientOnly",
                "InstallRules":[{"IsServer":False}],
            }),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"server-compatible"):
                module.project_palworld_activation(
                    {"environment_id":"palworld.windows-modded"},
                    [{"content_type":"workshop","managed_path":str(item),"activation":{"adapter":"palworld"}}],
                )

    def test_palworld_workshop_target_is_windows_safe(self):
        source=(ROOT/"dashboard"/"customer_content_workspace.py").read_text(encoding="utf-8")
        self.assertIn('if game_id=="palworld":payload["target"]=f"workshop/{resolved[\'published_file_id\']}"',source)


if __name__=="__main__":
    unittest.main()
