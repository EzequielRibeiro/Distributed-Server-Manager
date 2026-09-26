#!/usr/bin/env python3
"""Regressions: a new modpack file revises managed content, not the game server."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
for sub in ("core","dashboard","database"):
    path=str(ROOT/sub)
    if path not in sys.path:sys.path.insert(0,path)
from tests.minecraft_official_serverpack_upload_test import CONTEXT
from tests.universal_content_external_upload_test import service
from tests.universal_content_update_rollback_test import (
    UniversalContentUpdateRollbackTest as SQLiteFixture, _bundle, _member,
)


class ControllerIncrementalUpdateTest(unittest.TestCase):
    def test_preview_requires_same_project_minecraft_loader_and_exact_revision(self):
        s=service(status="completed")
        previous={"revision":3,"provider":"local","manifest_kind":"serverpack-local-v1",
                  "provider_project_id":"cf-1148445","provider_version_id":"file-123",
                  "minecraft_version":"26.1.2","loader_id":"neoforge",
                  "loader_version":"26.1.2.109"}
        s.content.history=[previous]
        bundle={"provider":"local","manifest_kind":"serverpack-local-v1",
                "provider_project_id":"cf-1148445","provider_version_id":"file-456",
                "minecraft_version":"26.1.2","loader_id":"neoforge",
                "loader_version":"26.1.2.109","members":[{"content_id":"mod-a"}]}
        plan=s._serverpack_revision_plan(CONTEXT,"atm11",bundle,3)
        self.assertEqual(plan["operation"],"update")
        self.assertEqual(plan["previous_revision"],3)
        self.assertTrue(plan["preserve_world"])
        self.assertTrue(plan["preserve_existing_config"])
        self.assertTrue(plan["requires_backup_confirmation"])
        with self.assertRaisesRegex(ValueError,"prévia"):
            s._serverpack_revision_plan(CONTEXT,"atm11",bundle,2)
        for key,bad in (("provider_project_id","cf-another"),
                        ("minecraft_version","26.2"),
                        ("loader_version","26.1.2.999"),
                        ("manifest_kind","mrpack-v1")):
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,"Migração|migração"):
                s._serverpack_revision_plan(CONTEXT,"atm11",{**bundle,key:bad},3)
        s.content.bundle_diff=lambda *args:{"added":["new"],"removed":[],"updated":[],"unchanged":[]}
        with self.assertRaisesRegex(ValueError,"versão já publicada"):
            s._serverpack_revision_plan(CONTEXT,"atm11",
                {**bundle,"provider_version_id":"file-123"},3)

    def test_same_official_file_with_unchanged_mods_is_a_noop(self):
        s=service(status="completed")
        s.content.history=[{"revision":6,"provider":"local",
            "manifest_kind":"serverpack-local-v1",
            "provider_project_id":"cf-1148445",
            "provider_version_id":"file-123",
            "minecraft_version":"26.1.2",
            "loader_id":"neoforge","loader_version":"26.1.2.109"}]
        s.content.bundle_diff=lambda *args:{
            "added":[],"removed":[],"updated":[],"unchanged":["same"]}
        candidate={"provider":"local","manifest_kind":"serverpack-local-v1",
            "provider_project_id":"cf-1148445","provider_version_id":"file-123",
            "minecraft_version":"26.1.2","loader_id":"neoforge",
            "loader_version":"26.1.2.109"}
        plan=s._serverpack_revision_plan(CONTEXT,"atm11",candidate,6)
        self.assertEqual(plan["operation"],"unchanged")
        self.assertFalse(plan["requires_backup_confirmation"])
        self.assertFalse(plan["requires_stopped_instance"])

    def test_new_content_id_does_not_create_second_active_modpack(self):
        s=service(status="completed")
        s.content.list=lambda **kwargs:[{"instance_id":"i1","content_id":"atm11",
            "content_type":"modpack","desired_state":"installed","activation_state":"enabled"}]
        with self.assertRaisesRegex(ValueError,"modpack ativo"):
            s._serverpack_capacity(CONTEXT,"atm11-copy",[])
        s._serverpack_capacity(CONTEXT,"atm11",[])

    def test_existing_bundle_stays_same_instance_and_retains_revision_rollback(self):
        owner=SQLiteFixture()
        owner.setUp()
        try:
            db=owner.repo
            v1=_bundle("v1",[_member("a"),_member("b")])
            old=db.put_bundle(owner.parent("1"),v1,[owner.child("a"),owner.child("b")])
            self.assertEqual(db.get("inst","pack")["metadata"]["activation"]["mode"],"bundle-parent")
            v2=_bundle("v2",[_member("a"),_member("b",digest="c"),_member("new")])
            self.assertEqual(db.bundle_diff("inst","pack",v2),
                {"added":["new"],"removed":[],"updated":["b"],"unchanged":["a"]})
            changed=db.put_bundle(owner.parent("2"),v2,
                [owner.child("a"),owner.child("b",version="2",digest="c"),owner.child("new")])
            self.assertEqual(changed["bundle_revision"],2)
            self.assertEqual(changed["assignment"]["instance_id"],"inst")
            self.assertEqual(changed["assignment"]["content_id"],"pack")
            self.assertEqual(changed["assignment"]["metadata"]["activation"]["mode"],
                             "bundle-parent-preserve-config")
            self.assertEqual(db.get("inst","a")["desired_state"],"installed")
            reverted=db.rollback_bundle("inst","pack",1,requested_by="owner",
                                        reason="unexpected gameplay regression")
            self.assertEqual(reverted["bundle_revision"],3)
            self.assertEqual(db.get("inst","pack")["version"],"1")
            self.assertEqual(db.get("inst","pack")["metadata"]["activation"]["mode"],
                             "bundle-parent-preserve-config")
            self.assertEqual(db.get("inst","new")["desired_state"],"absent")
        finally:
            owner.tearDown()


def load_activation(platform):
    path=ROOT/f"agents/{platform}/runtime/content_activation_minecraft.py"
    spec=importlib.util.spec_from_file_location(f"minecraft_incremental_{platform}",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentNonDestructiveProjectionTest(unittest.TestCase):
    def test_update_preserves_modified_configuration_and_world_on_both_platforms(self):
        for platform in ("linux","windows"):
            with self.subTest(platform=platform),tempfile.TemporaryDirectory() as td:
                module=load_activation(platform)
                base=Path(td);root=base/"game";root.mkdir()
                state=base/"state";(state/".dsm").mkdir(parents=True)
                existing=root/"config"/"user.toml";existing.parent.mkdir()
                existing.write_text("customer=customized")
                world=root/"world"/"region"/"region.mca"
                world.parent.mkdir(parents=True)
                world.write_bytes(b"KEEP ALL PLAYER AND WORLD DATA")
                module._write_override_manifest(
                    state/".dsm"/"content-activation-overrides.json",
                    {"config/user.toml":hashlib.sha256(b"published-original").hexdigest()})
                source=root/"content"/"modpacks"/"pack"/"server-overrides"/"config"
                source.mkdir(parents=True)
                (source/"user.toml").write_text("new-default=NOT_APPLIED")
                parent={"game_id":"minecraft","content_id":"pack","content_type":"modpack",
                        "managed_path":str(source.parent.parent),
                        "activation":{"adapter":"minecraft-java",
                                      "mode":"bundle-parent-preserve-config",
                                      "identifier":"server-overrides"}}
                spec={"game_id":"minecraft","content_projection":{},
                      "working_directory":str(root),"instance_state_root":str(state)}
                self.assertEqual(module.project_minecraft_files(spec,[parent]),[])
                projected=module.project_minecraft_bundle_overrides(spec,[parent])
                self.assertEqual(len(projected),1)
                self.assertTrue(projected[0]["preserve_existing_config"])
                spec["content_bundle_overrides"]=projected
                materialized=module.materialize_minecraft_overrides(spec)
                self.assertEqual(materialized,["config/user.toml"])
                self.assertEqual(existing.read_text(),"customer=customized")
                self.assertEqual(world.read_bytes(),b"KEEP ALL PLAYER AND WORLD DATA")
                self.assertEqual((source/"user.toml").read_text(),"new-default=NOT_APPLIED")

    def test_unchanged_jars_are_not_replaced_during_update(self):
        for platform in ("linux","windows"):
            with self.subTest(platform=platform),tempfile.TemporaryDirectory() as td:
                module=load_activation(platform)
                root=Path(td)/"game";root.mkdir()
                state=Path(td)/"state"
                target=root/"mods"/"capivara-mod-same.jar"
                target.parent.mkdir(parents=True)
                target.write_bytes(b"same-bytes")
                source=root/"content"/"mods"/"source.jar"
                source.parent.mkdir(parents=True)
                source.write_bytes(b"same-bytes")
                # Two equal artifacts with deliberately different metadata timestamps.
                import os
                os.utime(target,ns=(1_000_000_000,1_000_000_000))
                os.utime(source,ns=(2_000_000_000,2_000_000_000))
                module._write_manifest(state/".dsm"/"content-activation-files.json",
                                       ["mods/capivara-mod-same.jar"])
                spec={"game_id":"minecraft","content_projection":{},
                      "working_directory":str(root),"instance_state_root":str(state),
                      "content_file_projections":[{"content_id":"mod-same",
                        "managed_path":str(source),"target_stem":"mods/capivara-mod-same",
                        "extensions":[".jar"]}]}
                projected=module.materialize_minecraft_files(spec)
                self.assertEqual(projected,["mods/capivara-mod-same.jar"])
                self.assertEqual(target.stat().st_mtime_ns,1_000_000_000)
                source.write_bytes(b"updated-bytes")
                module.materialize_minecraft_files(spec)
                self.assertEqual(target.read_bytes(),b"updated-bytes")

    def test_existing_manifest_accepts_over_512_mods_without_reformat(self):
        for platform in ("linux","windows"):
            with self.subTest(platform=platform),tempfile.TemporaryDirectory() as td:
                module=load_activation(platform)
                path=Path(td)/"content-activation-files.json"
                items=[f"mods/capivara-member-{i}.jar" for i in range(700)]
                module._write_manifest(path,items)
                self.assertEqual(len(module._read_manifest(path)),700)


if __name__=="__main__":
    unittest.main()
