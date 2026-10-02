#!/usr/bin/env python3
"""Non-destructive original Minecraft mod filename regression coverage."""
from __future__ import annotations
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def adapter(platform):
    path = ROOT / "agents" / platform / "runtime" / "content_activation_minecraft.py"
    spec = importlib.util.spec_from_file_location("filename_adapter_" + platform, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def instance(root, filename, *, provider="curseforge", content_id="mb-synthetic",
             artifact_filename=None):
    runtime = root / "runtime"
    state = root / "state"
    state.mkdir(exist_ok=True)
    managed = runtime / "content" / content_id
    managed.mkdir(parents=True)
    (managed / filename).write_bytes(b"simulated mod bytes")
    spec = {
        "instance_id": "synthetic", "game_id": "minecraft",
        "environment_id": "minecraft.java.neoforge",
        "working_directory": str(runtime), "instance_state_root": str(state),
        "content_projection": {"adapter": "minecraft-java", "types": {
            "mod": {"directory": "mods", "extensions": [".jar"]}}},
    }
    entry = {"content_id": content_id, "content_type": "mod",
             "game_id": "minecraft", "managed_path": str(managed),
             "provider": provider}
    if artifact_filename is not None:
        entry["artifact_filename"] = artifact_filename
    return runtime, state, spec, entry


class OriginalMinecraftModFilenamesTest(unittest.TestCase):
    def test_supported_providers_keep_original_source_jar_name(self):
        for platform in ("linux", "windows"):
            for provider in ("curseforge", "modrinth", "local"):
                with self.subTest(platform=platform, provider=provider), tempfile.TemporaryDirectory() as tmp:
                    module = adapter(platform)
                    runtime, _, spec, entry = instance(Path(tmp), "Create-6.0.1-neoforge.jar", provider=provider)
                    item, = module.project_minecraft_files(spec, [entry])
                    self.assertEqual(item["target_name"], "mods/Create-6.0.1-neoforge.jar")
                    written = module.materialize_minecraft_files({
                        **spec, "content_file_projections": [item]})
                    self.assertEqual(written, ["mods/Create-6.0.1-neoforge.jar"])
                    self.assertEqual((runtime / "mods" / "Create-6.0.1-neoforge.jar").read_bytes(),
                                     b"simulated mod bytes")

    def test_existing_legacy_managed_name_never_changes(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = adapter(platform)
                runtime, state, spec, entry = instance(Path(tmp), "Real-Name.jar")
                manifest = state / ".dsm" / "content-activation-files.json"
                manifest.parent.mkdir()
                manifest.write_text(json.dumps({
                    "kind": "CapivaraContentFileProjection",
                    "schema_version": 1, "targets": ["mods/capivara-mb-synthetic.jar"],
                }))
                old = runtime / "mods" / "capivara-mb-synthetic.jar"
                old.parent.mkdir(); old.write_bytes(b"simulated mod bytes")
                item, = module.project_minecraft_files(spec, [entry])
                self.assertEqual(item["target_stem"], "mods/capivara-mb-synthetic")
                module.materialize_minecraft_files({**spec, "content_file_projections": [item]})
                self.assertEqual(old.read_bytes(), b"simulated mod bytes")
                self.assertFalse((runtime / "mods" / "Real-Name.jar").exists())

    def test_placeholder_filename_keeps_legacy_fallback(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = adapter(platform)
                _, _, spec, entry = instance(Path(tmp), "payload.jar")
                item, = module.project_minecraft_files(spec, [entry])
                self.assertEqual(item["target_stem"], "mods/capivara-mb-synthetic")

    def test_providerless_entries_keep_prior_behavior(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = adapter(platform)
                _, _, spec, entry = instance(Path(tmp), "Real-Name.jar", provider="")
                item, = module.project_minecraft_files(spec, [entry])
                self.assertEqual(item["target_stem"], "mods/capivara-mb-synthetic")

    def test_explicit_original_name_overrides_any_inference(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = adapter(platform)
                _, _, spec, entry = instance(Path(tmp), "payload.jar",
                                             artifact_filename="Actual-Mod-v2.jar")
                item, = module.project_minecraft_files(spec, [entry])
                self.assertEqual(item["target_name"], "mods/Actual-Mod-v2.jar")

    def test_same_original_name_conflict_keeps_existing_collision_strategy(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = adapter(platform)
                root = Path(tmp)
                runtime, _, spec, first = instance(root, "Original.jar", content_id="mod-one")
                _, _, _, second = instance(root, "Original.jar", content_id="mod-two")
                items = module.project_minecraft_files(spec, [first, second])
                self.assertEqual(items[0]["target_name"], "mods/Original.jar")
                self.assertNotEqual(items[1]["target_name"], items[0]["target_name"])
                self.assertTrue(items[1]["target_name"].startswith("mods/Original-"))
                paths = module.materialize_minecraft_files({**spec,"content_file_projections":items})
                self.assertEqual(len(paths),2)
                self.assertEqual((runtime / "mods" / "Original.jar").read_bytes(), b"simulated mod bytes")

    def test_invalid_inferred_filename_keeps_legacy_naming(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = adapter(platform)
                runtime, _, spec, entry = instance(Path(tmp), "initial.jar")
                original = Path(entry["managed_path"]) / "initial.jar"
                # No disk filenames exceeding filesystem limits are needed:
                # use a portable but forbidden leading-dot filename instead.
                bad = original.with_name(".hidden-mod.jar")
                original.rename(bad)
                item, = module.project_minecraft_files(spec, [entry])
                self.assertEqual(item["target_stem"], "mods/capivara-mb-synthetic")

    def test_unmanaged_original_name_is_not_overwritten(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                module = adapter(platform)
                runtime, _, spec, entry = instance(Path(tmp), "Original.jar")
                target = runtime / "mods" / "Original.jar"
                target.parent.mkdir(); target.write_bytes(b"customer-owned")
                projected = module.project_minecraft_files(spec, [entry])
                with self.assertRaises(module.MinecraftContentActivationError):
                    module.materialize_minecraft_files({
                        **spec,"content_file_projections":projected})
                self.assertEqual(target.read_bytes(), b"customer-owned")


if __name__ == "__main__":
    unittest.main()
