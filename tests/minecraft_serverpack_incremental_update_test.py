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

    def test_official_serverpack_updates_and_rollback_keep_existing_config(self):
        owner=SQLiteFixture()
        owner.setUp()
        try:
            db=owner.repo
            def pack(file_id,version_digest):
                member={"provider":"local","serverpack_child_v1":True,
                        "ephemeral_upload":True,"bundle_parent_content_id":"pack",
                        "bundle_member":"mods/example.jar","serverpack_loader":"neoforge",
                        "serverpack_loader_version":"26.1.2.109",
                        "sha256":version_digest*64,"size_bytes":8}
                parent={"instance_id":"inst","content_id":"pack","content_type":"modpack",
                        "provider":"local","version":file_id,
                        "artifact":{"provider":"local","archive":True,
                                    "package_id":"quarantine/"+file_id,
                                    "sha256":version_digest*64}}
                bundle={"provider":"local","provider_project_id":"cf-1148445",
                        "provider_version_id":"file-"+file_id,
                        "minecraft_version":"26.1.2","loader_id":"neoforge",
                        "loader_version":"26.1.2.109",
                        "manifest_kind":"serverpack-local-v1",
                        "members":[{"content_id":"example","path":"mods/example.jar",
                                    "required":True,"artifact":member}],
                        "override_roots":["server-overrides"]}
                child={"instance_id":"inst","content_id":"example",
                       "content_type":"mod","provider":"local",
                       "version":version_digest*32,"artifact":member,
                       "target":"mods/example","dependencies":["pack"]}
                return parent,bundle,[child]
            parent1,bundle1,children1=pack("1","a")
            initial=db.put_bundle(parent1,bundle1,children1)
            self.assertEqual(initial["assignment"]["metadata"]["activation"]["mode"],
                             "bundle-parent")
            parent2,bundle2,children2=pack("2","b")
            updated=db.put_bundle(parent2,bundle2,children2)
            self.assertEqual(updated["assignment"]["metadata"]["activation"]["mode"],
                             "bundle-parent-preserve-config")
            self.assertEqual(updated["assignment"]["instance_id"],"inst")
            self.assertEqual(updated["assignment"]["content_id"],"pack")
            self.assertEqual(db.get("inst","example")["version"],"b"*32)
            rolled=db.rollback_bundle("inst","pack",1,
                                      reason="new modpack version failed")
            self.assertEqual(rolled["bundle_revision"],3)
            self.assertEqual(db.get("inst","pack")["metadata"]["activation"]["mode"],
                             "bundle-parent-preserve-config")
            self.assertEqual(db.get("inst","example")["version"],"a"*32)
        finally:
            owner.tearDown()

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
                             "bundle-parent")
            self.assertEqual(db.get("inst","a")["desired_state"],"installed")
            reverted=db.rollback_bundle("inst","pack",1,requested_by="owner",
                                        reason="unexpected gameplay regression")
            self.assertEqual(reverted["bundle_revision"],3)
            self.assertEqual(db.get("inst","pack")["version"],"1")
            self.assertEqual(db.get("inst","pack")["metadata"]["activation"]["mode"],
                             "bundle-parent")
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

    def test_uploaded_modpack_cannot_replace_default_or_custom_world_data(self):
        """Both Agent backends must reject world payloads before any file changes."""
        suspicious = (
            "world/region/r.0.0.mca",
            "world_nether/DIM-1/region/r.0.0.mca",
            "world_the_end/DIM1/region/r.0.0.mca",
            "dimensions/minecraft/the_nether/region/r.0.0.mca",
            "survival/level.dat",
            "survival/region/r.0.0.mca",
            "survival_nether/region/r.0.0.mca",
            "survival_the_end/region/r.0.0.mca",
            "server.properties",
            "config/level.dat",
            "config/region/r.0.0.mca",
        )
        for platform in ("linux", "windows"):
            module = load_activation(platform)
            for attempted in suspicious:
                with self.subTest(platform=platform, payload=attempted), tempfile.TemporaryDirectory() as td:
                    base = Path(td)
                    root = base / "game"
                    root.mkdir()
                    state = base / "state"
                    state.mkdir()
                    props = root / "server.properties"
                    props.write_text("level-name=survival\\nmax-players=30\\n", encoding="utf-8")
                    sentinels = {}
                    for relative in (
                        "survival/level.dat",
                        "survival/region/r.0.0.mca",
                        "survival/playerdata/1234.dat",
                        "survival_nether/DIM-1/region/r.0.0.mca",
                        "survival_the_end/DIM1/region/r.0.0.mca",
                    ):
                        file = root / relative
                        file.parent.mkdir(parents=True, exist_ok=True)
                        file.write_bytes(("CUSTOMER WORLD: " + relative).encode())
                        sentinels[relative] = file.read_bytes()
                    source = root / "content" / "modpacks" / "pack"
                    target = source / "server-overrides" / attempted
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"UNTRUSTED MODPACK NEW WORLD")
                    spec = {
                        "game_id": "minecraft",
                        "content_projection": {},
                        "working_directory": str(root),
                        "instance_state_root": str(state),
                        "content_bundle_overrides": [{
                            "content_id": "pack",
                            "managed_path": str(source),
                            "roots": ["server-overrides"],
                        }],
                    }
                    with self.assertRaisesRegex(
                        module.MinecraftContentActivationError, "world|protected"
                    ):
                        module.materialize_minecraft_overrides(spec)
                    self.assertEqual(
                        props.read_text(encoding="utf-8"),
                        "level-name=survival\\nmax-players=30\\n"
                    )
                    for relative, expected in sentinels.items():
                        self.assertEqual((root / relative).read_bytes(), expected)

    def test_safe_modpack_config_import_keeps_custom_world(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as td:
                module = load_activation(platform)
                root = Path(td) / "game"
                root.mkdir()
                state = Path(td) / "state"
                state.mkdir()
                (root / "server.properties").write_text("level-name=My Survival\\n")
                marker = root / "My Survival" / "region" / "r.1.1.mca"
                marker.parent.mkdir(parents=True)
                marker.write_bytes(b"PERSISTENT REGION")
                source = root / "content" / "modpacks" / "pack"
                config = source / "server-overrides" / "config" / "new-mod.toml"
                config.parent.mkdir(parents=True)
                config.write_text("new-feature=true")
                spec = {
                    "game_id": "minecraft",
                    "content_projection": {},
                    "working_directory": str(root),
                    "instance_state_root": str(state),
                    "content_bundle_overrides": [{
                        "content_id": "pack",
                        "managed_path": str(source),
                        "roots": ["server-overrides"],
                    }],
                }
                self.assertEqual(
                    module.materialize_minecraft_overrides(spec),
                    ["config/new-mod.toml"]
                )
                self.assertEqual(marker.read_bytes(), b"PERSISTENT REGION")
                self.assertEqual(
                    (root / "server.properties").read_text(), "level-name=My Survival\\n"
                )

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
