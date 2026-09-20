#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,tempfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MODULE_PATH=ROOT/"agents"/"linux"/"runtime"/"content_activation_runtime.py"

def load_runtime(name):
    spec=importlib.util.spec_from_file_location(name,MODULE_PATH)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class M10ContentPersistenceAfterRestartTest(unittest.TestCase):
    def base_spec(self,root):
        return {
            "instance_id":"i1",
            "arguments":["-config=server.cfg"],
            "working_directory":str(root/"server"),
            "instance_state_root":str(root/"state"),
        }

    def test_dayz_snapshot_rehydrates_without_argument_duplication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"server").mkdir();a=root/"state"/"content"/"a";b=root/"state"/"content"/"b";a.mkdir(parents=True);b.mkdir(parents=True)
            snapshot={"checksum":"dayz-persisted","entries":[
                {"content_id":"a","game_id":"dayz","package_id":"221100:111","managed_path":str(a),"activation":{"mode":"mod"}},
                {"content_id":"b","game_id":"dayz","package_id":"221100:222","managed_path":str(b),"activation":{"mode":"server-mod"}},
            ]}
            first=load_runtime("m10_dayz_first").project_runtime_spec(self.base_spec(root),snapshot)
            restarted=load_runtime("m10_dayz_restarted")
            second=restarted.project_runtime_spec(first,snapshot)
            self.assertEqual(second["content_activation_checksum"],"dayz-persisted")
            self.assertEqual(second["content_base_arguments"],["-config=server.cfg"])
            self.assertEqual(second["arguments"],["-config=server.cfg","-mod=@dsm-i1-111","-serverMod=@dsm-i1-222"])
            self.assertEqual(second["arguments"].count("-mod=@dsm-i1-111"),1)
            self.assertEqual(second["arguments"].count("-serverMod=@dsm-i1-222"),1)
            self.assertEqual([item["alias"] for item in second["content_dayz_mod_aliases"]],["@dsm-i1-111","@dsm-i1-222"])

    def test_project_zomboid_snapshot_rematerializes_idempotently_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/"server").mkdir();(root/"state").mkdir()
            snapshot={"checksum":"pz-persisted","entries":[
                {"content_id":"a","game_id":"projectzomboid","package_id":"108600:111","activation":{"identifier":"Alpha"}},
                {"content_id":"b","game_id":"projectzomboid","package_id":"108600:222","activation":{"identifier":"Beta"}},
            ]}
            first_runtime=load_runtime("m10_pz_first")
            first=first_runtime.project_runtime_spec(self.base_spec(root),snapshot)
            first_runtime.materialize_content_activation(first)
            target=root/"state"/"Zomboid"/"Server"/"servertest.ini"
            before=target.read_text(encoding="utf-8")
            restarted=load_runtime("m10_pz_restarted")
            second=restarted.project_runtime_spec(first,snapshot)
            restarted.materialize_content_activation(second)
            after=target.read_text(encoding="utf-8")
            self.assertEqual(second["content_activation_checksum"],"pz-persisted")
            self.assertEqual(before,after)
            self.assertIn("WorkshopItems=111;222",after)
            self.assertIn("Mods=Alpha;Beta",after)

if __name__=="__main__":
    unittest.main()
