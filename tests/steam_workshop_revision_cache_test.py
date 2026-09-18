#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for path in (
    ROOT,
    ROOT / "core",
    ROOT / "database",
    ROOT / "dashboard",
    ROOT / "agents" / "linux" / "runtime",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import content_provider_steam_workshop as workshop_provider
import content_cache_inventory
import customer_content_workspace as workspace_module
from content_repository import ContentRepository


class SteamWorkshopRevisionCacheTest(unittest.TestCase):
    def _write_manifest(self, source: Path, app_id: str, item_id: str, revision: str) -> Path:
        manifest = source.parent.parent.parent / f"appworkshop_{app_id}.acf"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            '"AppWorkshop"\n{\n'
            f'  "AppID" "{app_id}"\n'
            '  "WorkshopItemsInstalled"\n  {\n'
            f'    "{item_id}"\n    {{\n'
            f'      "timeupdated" "{revision}"\n'
            '    }\n  }\n}\n',
            encoding="utf-8",
        )
        return manifest

    def setUp(self):
        self._state_tmp = tempfile.TemporaryDirectory()
        self._state_env = patch.dict(
            "os.environ",
            {"CAPIVARA_AGENT_STATE_DIR": self._state_tmp.name},
            clear=False,
        )
        self._state_env.start()

    def tearDown(self):
        self._state_env.stop()
        self._state_tmp.cleanup()

    def test_controller_persists_canonical_workshop_revision(self):
        service = workspace_module.CustomerContentWorkspaceService.__new__(
            workspace_module.CustomerContentWorkspaceService
        )
        service.workspace = SimpleNamespace(root=ROOT)
        service.workshop_resolver = lambda reference, expected_app_id: {
            "provider": "steam-workshop",
            "package_id": "221100:1828439124",
            "published_file_id": "1828439124",
            "consumer_app_id": "221100",
            "metadata": {
                "published_file_id": "1828439124",
                "consumer_app_id": "221100",
                "time_updated": 1785000000,
                "title": "VPPAdminTools",
            },
        }
        payload = {
            "content_type": "workshop",
            "provider": "steam-workshop",
            "artifact": {
                "provider": "steam-workshop",
                "package_id": "1828439124",
            },
            "metadata": {},
            "provenance": {},
        }
        with patch.object(
            workspace_module,
            "runtime_definition",
            return_value={
                "content": {
                    "steam_workshop": {
                        "app_id": "221100",
                    }
                }
            },
        ):
            result = service._resolve_workshop(
                {
                    "runtime_id": "dayz.stable",
                    "game_id": "dayz",
                },
                payload,
            )

        self.assertIs(result, payload)
        self.assertEqual(payload["version"], "1785000000")
        self.assertEqual(payload["artifact"]["revision"], "1785000000")
        self.assertEqual(
            payload["artifact"]["package_id"],
            "221100:1828439124",
        )

    def test_second_instance_reuses_revision_cache_without_steamcmd(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_root = root / "state"
            game_data_root = state_root / "game-data"
            source = (
                root
                / "home"
                / ".local"
                / "share"
                / "Steam"
                / "steamapps"
                / "workshop"
                / "content"
                / "221100"
                / "1828439124"
            )
            source.mkdir(parents=True)
            (source / "mod.cpp").write_text("name=VPP;\n", encoding="utf-8")
            self._write_manifest(source, "221100", "1828439124", "1785000000")
            executable = root / "steamcmd" / "steamcmd.sh"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            artifact = {
                "provider": "steam-workshop",
                "package_id": "221100:1828439124",
                "revision": "1785000000",
            }
            completed = SimpleNamespace(returncode=0, stdout="Success")

            with (
                patch.dict("os.environ", {"HOME": str(root / "home")}, clear=False),
                patch.object(workshop_provider, "_steamcmd", return_value=str(executable)),
                patch.object(workshop_provider.subprocess, "run", return_value=completed) as run,
            ):
                first = workshop_provider.resolve_steam_workshop(
                    artifact,
                    root / "stage-a",
                    game_data_root,
                )
                second = workshop_provider.resolve_steam_workshop(
                    artifact,
                    root / "stage-b",
                    game_data_root,
                )

            expected = (
                state_root
                / "provider-cache"
                / "steam-workshop"
                / "221100"
                / "1828439124"
                / "revisions"
                / "1785000000"
            ).resolve()
            self.assertEqual(first, expected)
            self.assertEqual(second, expected)
            self.assertTrue((expected / "mod.cpp").is_file())
            self.assertEqual(run.call_count, 1)

    def test_revision_cache_prunes_oldest_entries_and_keeps_current(self):
        with tempfile.TemporaryDirectory() as td:
            revisions = Path(td) / "revisions"
            revisions.mkdir()
            for revision in ("100", "200", "300", "400", "500"):
                path = revisions / revision
                path.mkdir()
                (path / "marker").write_text(revision, encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"CAPIVARA_WORKSHOP_CACHE_REVISIONS": "3"},
                clear=False,
            ):
                removed = workshop_provider._prune_revision_cache(
                    revisions,
                    keep_revision="500",
                )

            self.assertEqual(set(removed), {"100", "200"})
            self.assertEqual(
                {path.name for path in revisions.iterdir() if path.is_dir()},
                {"300", "400", "500"},
            )

    def test_retention_is_lossless_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            revisions = Path(td) / "revisions"
            revisions.mkdir()
            for revision in ("100", "200", "300", "400"):
                (revisions / revision).mkdir()

            with patch.dict("os.environ", {}, clear=False):
                previous = __import__("os").environ.pop(
                    "CAPIVARA_WORKSHOP_CACHE_REVISIONS",
                    None,
                )
                try:
                    removed = workshop_provider._prune_revision_cache(
                        revisions,
                        keep_revision="400",
                    )
                    limit = workshop_provider._retention_limit()
                finally:
                    if previous is not None:
                        __import__("os").environ[
                            "CAPIVARA_WORKSHOP_CACHE_REVISIONS"
                        ] = previous

            self.assertIsNone(limit)
            self.assertEqual(removed, [])
            self.assertEqual(
                {path.name for path in revisions.iterdir() if path.is_dir()},
                {"100", "200", "300", "400"},
            )

    def test_retention_limit_never_drops_below_two_when_enabled(self):
        with patch.dict(
            "os.environ",
            {"CAPIVARA_WORKSHOP_CACHE_REVISIONS": "1"},
            clear=False,
        ):
            self.assertEqual(workshop_provider._retention_limit(), 2)

        with patch.dict(
            "os.environ",
            {"CAPIVARA_WORKSHOP_CACHE_REVISIONS": "7"},
            clear=False,
        ):
            self.assertEqual(workshop_provider._retention_limit(), 7)

    def test_controller_derives_protected_revisions_from_u9_history(self):
        repository = ContentRepository.__new__(ContentRepository)
        repository.history = lambda assignment_id: [
            {
                "version": "1785000000",
                "artifact": {
                    "provider": "steam-workshop",
                    "package_id": "221100:1828439124",
                    "revision": "1785000000",
                },
            },
            {
                "version": "1784000000",
                "artifact": {
                    "provider": "steam-workshop",
                    "package_id": "221100:1828439124",
                    "revision": "1784000000",
                },
            },
            {
                "version": "999",
                "artifact": {
                    "provider": "steam-workshop",
                    "package_id": "221100:9999999999",
                    "revision": "999",
                },
            },
        ]
        assignment = {
            "assignment_id": "assignment-1",
            "provider": "steam-workshop",
            "version": "1785000000",
            "artifact": {
                "provider": "steam-workshop",
                "package_id": "221100:1828439124",
                "revision": "1785000000",
            },
        }

        self.assertEqual(
            repository._protected_workshop_revisions(assignment),
            ["1784000000", "1785000000"],
        )

    def test_prune_never_removes_controller_protected_revisions(self):
        with tempfile.TemporaryDirectory() as td:
            revisions = Path(td) / "revisions"
            revisions.mkdir()
            for revision in ("100", "200", "300", "400", "500", "600"):
                path = revisions / revision
                path.mkdir()
                (path / "marker").write_text(revision, encoding="utf-8")

            with patch.dict(
                "os.environ",
                {"CAPIVARA_WORKSHOP_CACHE_REVISIONS": "2"},
                clear=False,
            ):
                removed = workshop_provider._prune_revision_cache(
                    revisions,
                    keep_revision="600",
                    protected_revisions={"100", "300"},
                )

            remaining = {
                path.name
                for path in revisions.iterdir()
                if path.is_dir()
            }
            self.assertIn("100", remaining)
            self.assertIn("300", remaining)
            self.assertIn("600", remaining)
            self.assertEqual(remaining, {"100", "300", "500", "600"})
            self.assertEqual(set(removed), {"200", "400"})

    def test_protected_revision_payload_is_fail_closed(self):
        self.assertEqual(
            workshop_provider._protected_revisions(
                {"protected_revisions": ["100", "200", "100"]}
            ),
            {"100", "200"},
        )
        with self.assertRaisesRegex(ValueError, "protected revision must be numeric"):
            workshop_provider._protected_revisions(
                {"protected_revisions": ["100", "../bad"]}
            )

    def test_concurrent_same_revision_runs_steamcmd_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_root = root / "state"
            game_data_root = state_root / "game-data"
            source = (
                root
                / "home"
                / ".local"
                / "share"
                / "Steam"
                / "steamapps"
                / "workshop"
                / "content"
                / "221100"
                / "1828439124"
            )
            source.mkdir(parents=True)
            (source / "mod.cpp").write_text("name=VPP;\n", encoding="utf-8")
            self._write_manifest(source, "221100", "1828439124", "1785000000")
            executable = root / "steamcmd" / "steamcmd.sh"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            artifact = {
                "provider": "steam-workshop",
                "package_id": "221100:1828439124",
                "revision": "1785000000",
            }
            call_count = 0
            count_lock = threading.Lock()

            def fake_run(*args, **kwargs):
                nonlocal call_count
                with count_lock:
                    call_count += 1
                time.sleep(0.15)
                return SimpleNamespace(returncode=0, stdout="Success")

            results = []
            errors = []

            def worker():
                try:
                    results.append(
                        workshop_provider.resolve_steam_workshop(
                            artifact,
                            root / "stage",
                            game_data_root,
                        )
                    )
                except Exception as exc:
                    errors.append(exc)

            with (
                patch.dict("os.environ", {"HOME": str(root / "home")}, clear=False),
                patch.object(workshop_provider, "_steamcmd", return_value=str(executable)),
                patch.object(workshop_provider.subprocess, "run", side_effect=fake_run),
            ):
                threads = [threading.Thread(target=worker) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

            self.assertFalse(errors)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0], results[1])
            self.assertEqual(call_count, 1)
            self.assertTrue(results[0].is_dir())

    def test_revision_lookup_skips_stale_cache_and_uses_later_matching_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            game_data_root = root / "state" / "game-data"
            executable = root / "steamcmd" / "steamcmd.sh"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")

            stale = (
                executable.parent
                / "steamapps" / "workshop" / "content" / "221100" / "1828439124"
            )
            stale.mkdir(parents=True)
            (stale / "mod.cpp").write_text("stale\n", encoding="utf-8")
            self._write_manifest(stale, "221100", "1828439124", "1784000000")

            home = root / "home"
            valid = (
                home / ".steam" / "steamcmd"
                / "steamapps" / "workshop" / "content" / "221100" / "1828439124"
            )
            valid.mkdir(parents=True)
            (valid / "mod.cpp").write_text("current\n", encoding="utf-8")
            self._write_manifest(valid, "221100", "1828439124", "1785000000")

            artifact = {
                "provider": "steam-workshop",
                "package_id": "221100:1828439124",
                "revision": "1785000000",
            }
            with (
                patch.dict("os.environ", {"HOME": str(home)}, clear=False),
                patch.object(workshop_provider, "_steamcmd", return_value=str(executable)),
                patch.object(
                    workshop_provider.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout="Success"),
                ),
            ):
                result = workshop_provider.resolve_steam_workshop(
                    artifact,
                    root / "stage",
                    game_data_root,
                )

            self.assertTrue(result.is_dir())
            self.assertEqual(
                (result / "mod.cpp").read_text(encoding="utf-8"),
                "current\n",
            )

    def test_revision_snapshot_fails_closed_when_manifest_revision_mismatches(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state_root = root / "state"
            game_data_root = state_root / "game-data"
            source = (
                root / "home" / ".local" / "share" / "Steam"
                / "steamapps" / "workshop" / "content" / "221100" / "1828439124"
            )
            source.mkdir(parents=True)
            (source / "mod.cpp").write_text("name=VPP;\n", encoding="utf-8")
            self._write_manifest(source, "221100", "1828439124", "1784000000")
            executable = root / "steamcmd" / "steamcmd.sh"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            artifact = {
                "provider": "steam-workshop",
                "package_id": "221100:1828439124",
                "revision": "1785000000",
            }
            with (
                patch.dict("os.environ", {"HOME": str(root / "home")}, clear=False),
                patch.object(workshop_provider, "_steamcmd", return_value=str(executable)),
                patch.object(
                    workshop_provider.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout="Success"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "revision mismatch"):
                    workshop_provider.resolve_steam_workshop(
                        artifact,
                        root / "stage",
                        game_data_root,
                    )
            expected = (
                state_root / "provider-cache" / "steam-workshop" / "221100"
                / "1828439124" / "revisions" / "1785000000"
            )
            self.assertFalse(expected.exists())

    def test_revision_snapshot_fails_closed_when_manifest_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = (
                root / "home" / ".local" / "share" / "Steam"
                / "steamapps" / "workshop" / "content" / "221100" / "1828439124"
            )
            source.mkdir(parents=True)
            (source / "mod.cpp").write_text("name=VPP;\n", encoding="utf-8")
            executable = root / "steamcmd" / "steamcmd.sh"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            artifact = {
                "provider": "steam-workshop",
                "package_id": "221100:1828439124",
                "revision": "1785000000",
            }
            with (
                patch.dict("os.environ", {"HOME": str(root / "home")}, clear=False),
                patch.object(workshop_provider, "_steamcmd", return_value=str(executable)),
                patch.object(
                    workshop_provider.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout="Success"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "manifest is unavailable"):
                    workshop_provider.resolve_steam_workshop(
                        artifact,
                        root / "stage",
                        root / "state" / "game-data",
                    )

    def test_revision_snapshot_fails_closed_when_manifest_metadata_is_malformed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = (
                root / "home" / ".local" / "share" / "Steam"
                / "steamapps" / "workshop" / "content" / "221100" / "1828439124"
            )
            source.mkdir(parents=True)
            (source / "mod.cpp").write_text("name=VPP;\n", encoding="utf-8")
            manifest = source.parent.parent.parent / "appworkshop_221100.acf"
            manifest.write_text(
                '"AppWorkshop"\n{\n  "WorkshopItemsInstalled"\n  {\n'
                '    "1828439124"\n    {\n      "size" "123"\n    }\n  }\n}\n',
                encoding="utf-8",
            )
            executable = root / "steamcmd" / "steamcmd.sh"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            artifact = {
                "provider": "steam-workshop",
                "package_id": "221100:1828439124",
                "revision": "1785000000",
            }
            with (
                patch.dict("os.environ", {"HOME": str(root / "home")}, clear=False),
                patch.object(workshop_provider, "_steamcmd", return_value=str(executable)),
                patch.object(
                    workshop_provider.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0, stdout="Success"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "revision metadata is unavailable"):
                    workshop_provider.resolve_steam_workshop(
                        artifact,
                        root / "stage",
                        root / "state" / "game-data",
                    )

    def test_cache_inventory_reports_events_revisions_and_bytes(self):
        state_root = Path(self._state_tmp.name)
        revision = (
            state_root
            / "provider-cache"
            / "steam-workshop"
            / "221100"
            / "1828439124"
            / "revisions"
            / "1785000000"
        )
        revision.mkdir(parents=True)
        payload = b"capivara-cache"
        (revision / "mod.cpp").write_bytes(payload)

        content_cache_inventory.record_cache_event("miss")
        content_cache_inventory.record_cache_event("download")
        content_cache_inventory.record_cache_event("hit")
        snapshot = content_cache_inventory.snapshot()

        self.assertEqual(snapshot["kind"], "ContentCacheInventory")
        self.assertEqual(snapshot["provider"], "steam-workshop")
        self.assertEqual(snapshot["hits"], 1)
        self.assertEqual(snapshot["misses"], 1)
        self.assertEqual(snapshot["downloads"], 1)
        self.assertEqual(snapshot["avoided_downloads"], 1)
        self.assertEqual(snapshot["items"], 1)
        self.assertEqual(snapshot["revisions"], 1)
        self.assertEqual(snapshot["bytes"], len(payload))

    def test_invalid_revision_is_rejected_before_provider_execution(self):
        artifact = {
            "provider": "steam-workshop",
            "package_id": "221100:1828439124",
            "revision": "../bad",
        }
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "revision must be numeric"):
                workshop_provider.resolve_steam_workshop(
                    artifact,
                    Path(td) / "stage",
                    Path(td) / "state" / "game-data",
                )


if __name__ == "__main__":
    unittest.main()
