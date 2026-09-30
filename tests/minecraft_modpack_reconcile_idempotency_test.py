#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def checksum(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def load(platform: str):
    path = ROOT / "agents" / platform / "runtime" / "content_activation_minecraft.py"
    spec = importlib.util.spec_from_file_location(
        f"minecraft_modpack_reconcile_{platform}", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MinecraftModpackReconcileIdempotencyTest(unittest.TestCase):

    def _fixture(self, platform: str):
        module = load(platform)
        temp = tempfile.TemporaryDirectory()
        base = Path(temp.name)
        runtime = base / "runtime"
        state = base / "state"
        source = runtime / "content" / "modpacks" / "pack"

        runtime.mkdir()
        state.mkdir()

        config = source / "server-overrides" / "config"
        config.mkdir(parents=True)
        (config / "mutable.toml").write_text("published=true\n")
        (config / "removed.toml").write_text("published=true\n")

        item = {
            "content_id": "pack",
            "managed_path": str(source),
            "roots": ["server-overrides"],
            "preserve_existing_config": False,
        }

        return temp, module, runtime, state, item

    def test_first_materialization_writes_v2_projection_identity(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                temp, module, runtime, state, item = self._fixture(platform)
                try:
                    projection = checksum("projection-v1")
                    spec = {
                        "game_id": "minecraft",
                        "environment_id": "minecraft.java.neoforge",
                        "working_directory": str(runtime),
                        "instance_state_root": str(state),
                        "content_activation_checksum": projection,
                        "content_bundle_overrides": [item],
                    }

                    written = module.materialize_minecraft_overrides(spec)

                    self.assertEqual(
                        written,
                        ["config/mutable.toml", "config/removed.toml"],
                    )

                    manifest = json.loads(
                        (state / ".dsm" / "content-activation-overrides.json").read_text()
                    )
                    self.assertEqual(manifest["schema_version"], 2)
                    self.assertEqual(
                        manifest["kind"], "CapivaraContentOverrideProjection"
                    )
                    self.assertRegex(manifest["bundle_seed_checksum"], r"^[0-9a-f]{64}$")
                    self.assertNotEqual(manifest["bundle_seed_checksum"], projection)
                    self.assertEqual(len(manifest["targets"]), 2)
                finally:
                    temp.cleanup()

    def test_same_projection_preserves_runtime_mutation_and_deletion(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                temp, module, runtime, state, item = self._fixture(platform)
                try:
                    projection = checksum("projection-v1")
                    spec = {
                        "game_id": "minecraft",
                        "environment_id": "minecraft.java.neoforge",
                        "working_directory": str(runtime),
                        "instance_state_root": str(state),
                        "content_activation_checksum": projection,
                        "content_bundle_overrides": [item],
                    }

                    module.materialize_minecraft_overrides(spec)

                    mutable = runtime / "config" / "mutable.toml"
                    removed = runtime / "config" / "removed.toml"

                    mutable.write_text("runtime-modified=true\n")
                    removed.unlink()

                    # An unrelated activation entry may change the global snapshot checksum.
                    # Bundle idempotency must depend on the bundle seed, not that global value.
                    spec["content_activation_checksum"] = checksum("unrelated-child-change")
                    result = module.materialize_minecraft_overrides(spec)

                    self.assertEqual(
                        result,
                        ["config/mutable.toml", "config/removed.toml"],
                    )
                    self.assertEqual(
                        mutable.read_text(), "runtime-modified=true\n"
                    )
                    self.assertFalse(removed.exists())
                finally:
                    temp.cleanup()

    def test_different_projection_does_not_bypass_local_edit_protection(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                temp, module, runtime, state, item = self._fixture(platform)
                try:
                    first = {
                        "game_id": "minecraft",
                        "environment_id": "minecraft.java.neoforge",
                        "working_directory": str(runtime),
                        "instance_state_root": str(state),
                        "content_activation_checksum": checksum("projection-v1"),
                        "content_bundle_overrides": [item],
                    }
                    module.materialize_minecraft_overrides(first)

                    mutable = runtime / "config" / "mutable.toml"
                    mutable.write_text("runtime-modified=true\n")

                    changed = dict(first)
                    source_file = Path(item["managed_path"]) / "server-overrides" / "config" / "mutable.toml"
                    source_file.write_text("published=v2\n")

                    with self.assertRaisesRegex(
                        module.MinecraftContentActivationError,
                        "modified locally",
                    ):
                        module.materialize_minecraft_overrides(changed)

                    self.assertEqual(
                        mutable.read_text(), "runtime-modified=true\n"
                    )
                finally:
                    temp.cleanup()

    def test_v1_exact_seed_migrates_without_touching_live_runtime(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                temp, module, runtime, state, item = self._fixture(platform)
                try:
                    spec = {
                        "game_id": "minecraft",
                        "environment_id": "minecraft.java.neoforge",
                        "working_directory": str(runtime),
                        "instance_state_root": str(state),
                        "content_activation_checksum": checksum("projection-v1"),
                        "content_bundle_overrides": [item],
                    }
                    module.materialize_minecraft_overrides(spec)
                    manifest_path = state / ".dsm" / "content-activation-overrides.json"
                    manifest = json.loads(manifest_path.read_text())
                    manifest.pop("bundle_seed_checksum")
                    manifest["schema_version"] = 1
                    manifest_path.write_text(json.dumps(manifest))

                    mutable = runtime / "config" / "mutable.toml"
                    removed = runtime / "config" / "removed.toml"
                    mutable.write_text("runtime-modified=true\n")
                    removed.unlink()

                    module.materialize_minecraft_overrides(spec)

                    migrated = json.loads(manifest_path.read_text())
                    self.assertEqual(migrated["schema_version"], 2)
                    self.assertRegex(migrated["bundle_seed_checksum"], r"^[0-9a-f]{64}$")
                    self.assertEqual(mutable.read_text(), "runtime-modified=true\n")
                    self.assertFalse(removed.exists())
                finally:
                    temp.cleanup()

    def test_untouched_runtime_seed_can_be_replaced_on_first_projection(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                temp, module, runtime, state, item = self._fixture(platform)
                try:
                    seed = Path(temp.name) / "seed"
                    seed_file = seed / "config" / "mutable.toml"
                    seed_file.parent.mkdir(parents=True)
                    seed_file.write_text("runtime-default=true\n")
                    target = runtime / "config" / "mutable.toml"
                    target.parent.mkdir(parents=True)
                    target.write_text("runtime-default=true\n")

                    spec = {
                        "game_id": "minecraft",
                        "environment_id": "minecraft.java.neoforge",
                        "working_directory": str(runtime),
                        "instance_state_root": str(state),
                        "profile_context": {"install_path": str(seed)},
                        "content_bundle_overrides": [item],
                    }
                    module.materialize_minecraft_overrides(spec)
                    self.assertEqual(target.read_text(), "published=true\n")
                finally:
                    temp.cleanup()

    def test_disable_still_removes_unchanged_owned_targets(self):
        for platform in ("linux", "windows"):
            with self.subTest(platform=platform):
                temp, module, runtime, state, item = self._fixture(platform)
                try:
                    first = {
                        "game_id": "minecraft",
                        "environment_id": "minecraft.java.neoforge",
                        "working_directory": str(runtime),
                        "instance_state_root": str(state),
                        "content_activation_checksum": checksum("projection-v1"),
                        "content_bundle_overrides": [item],
                    }
                    module.materialize_minecraft_overrides(first)

                    disabled = dict(first)
                    disabled["content_activation_checksum"] = checksum("projection-off")
                    disabled["content_bundle_overrides"] = []

                    self.assertEqual(
                        module.materialize_minecraft_overrides(disabled), []
                    )
                    self.assertFalse(
                        (runtime / "config" / "mutable.toml").exists()
                    )
                    self.assertFalse(
                        (runtime / "config" / "removed.toml").exists()
                    )
                finally:
                    temp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
