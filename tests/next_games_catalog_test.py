#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LINUX_RUNTIME = ROOT / "agents/linux/runtime"
if str(LINUX_RUNTIME) not in sys.path:
    sys.path.insert(0, str(LINUX_RUNTIME))

from profiles.registry import resolve_profile, supported_profiles


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NextGamesCatalogTest(unittest.TestCase):
    def test_supported_and_deferred_decisions_are_explicit(self):
        matrix = load(ROOT / "catalog/v2/support-matrix.json")
        published = {row["id"] for row in matrix["published_runtimes"]}
        deferred = {row["id"] for row in matrix["deferred_runtimes"]}
        self.assertTrue({
            "sevendaystodie.stable", "satisfactory.stable", "garrysmod.stable",
            "factorio.stable", "left4dead2.stable", "armareforger.stable",
        } <= published)
        self.assertTrue({
            "fivem.stable", "valheim.stable", "arksurvivalascended.stable", "theisle.stable",
        } <= deferred)
        self.assertTrue(published.isdisjoint(deferred))

    def test_artifact_contracts_match_known_dedicated_distributions(self):
        expected = {
            "sevendaystodie": ("294420", "7DaysToDieServer.x86_64"),
            "satisfactory": ("1690800", "FactoryServer.sh"),
            "garrysmod": ("4020", "srcds_run"),
            "left4dead2": ("222860", "srcds_run"),
            "armareforger": ("1874900", "ArmaReforgerServer"),
        }
        for game, (app_id, executable) in expected.items():
            runtime = load(ROOT / f"catalog/v2/games/{game}/runtimes/stable.json")
            self.assertEqual(runtime["artifact"]["provider"], "steam")
            self.assertEqual(runtime["artifact"]["package_id"], app_id)
            self.assertEqual(runtime["process"]["executable"], executable)
            self.assertEqual(runtime["requirements"]["os"], ["linux"])
        factorio = load(ROOT / "catalog/v2/games/factorio/runtimes/stable.json")
        self.assertEqual(factorio["artifact"]["provider"], "http-archive")
        self.assertEqual(factorio["artifact"]["url"], "https://www.factorio.com/get-download/stable/headless/linux64")

    def test_protocols_may_share_numeric_port_but_not_protocol_offset_pair(self):
        for game in ("sevendaystodie", "satisfactory", "garrysmod", "left4dead2"):
            runtime = load(ROOT / f"catalog/v2/games/{game}/runtimes/stable.json")
            ports = runtime["network"]["ports"]
            pairs = [(item["protocol"], item["offset"]) for item in ports]
            self.assertEqual(len(pairs), len(set(pairs)))
            self.assertTrue(all(0 <= item["offset"] < runtime["network"]["block_size"] for item in ports))

    def test_registry_exposes_only_intended_new_profiles(self):
        names = set(supported_profiles())
        for key in (
            "sevendaystodie.stable", "factorio.stable", "armareforger.stable",
            "satisfactory.stable", "garrysmod.stable", "left4dead2.stable",
        ):
            self.assertIn(key, names)
        for key in ("fivem.stable", "valheim.stable", "arksurvivalascended.stable", "theisle.stable"):
            self.assertNotIn(key, names)

    def test_source_profile_keeps_port_as_two_argv_elements(self):
        profile = resolve_profile({"environment_id": "garrysmod.stable", "game_id": "garrysmod"})
        spec = profile.build_runtime_spec(
            {"instance_id": "gmod-1", "agent_id": "agent-1", "game_id": "garrysmod", "environment_id": "garrysmod.stable"},
            {
                "install_path": "/opt/dsm/game-data/garrysmod/serverfiles",
                "instance_state_root": "/var/lib/capivara-instances/gmod-1",
                "ports": {"game_udp": {"port": 27015, "protocol": "udp"}, "game_tcp": {"port": 27015, "protocol": "tcp"}},
                "catalog_runtime_policy": {"runtime_id": "garrysmod.stable", "executable": "srcds_run", "working_directory": "."},
            },
        )
        self.assertEqual(spec["arguments"][:2], ["-port", "27015"])
        self.assertFalse(any(item == "-port 27015" for item in spec["arguments"]))

    def test_seven_days_xml_preparer_is_idempotent_and_private(self):
        module = load_module("sevendaystodie_prepare_tested", LINUX_RUNTIME / "sevendaystodie_prepare.py")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "serverconfig.xml"
            path.write_text('<ServerSettings><property name="ServerPort" value="26900" /></ServerSettings>', encoding="utf-8")
            module.prepare(str(path), 28000)
            module.prepare(str(path), 28000)
            text = path.read_text(encoding="utf-8")
            self.assertIn('name="ServerPort" value="28000"', text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_armareforger_preparer_writes_no_admin_secret(self):
        module = load_module("armareforger_prepare_tested", LINUX_RUNTIME / "armareforger_prepare.py")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "server.json"
            module.prepare(str(path), 2001, 17777, "Capivara Test")
            payload = load(path)
            self.assertEqual(payload["bindPort"], 2001)
            self.assertEqual(payload["a2s"]["port"], 17777)
            self.assertEqual(payload["game"]["password"], "")
            self.assertEqual(payload["game"]["passwordAdmin"], "")

    def test_factorio_preparer_creates_settings_and_one_save(self):
        module = load_module("factorio_prepare_tested", LINUX_RUNTIME / "factorio_prepare.py")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            binary = root / "factorio"
            binary.write_text("stub", encoding="utf-8")
            save = root / "state/saves/capivara.zip"
            settings = root / "state/config/server-settings.json"
            def fake_run(argv, **kwargs):
                save.parent.mkdir(parents=True, exist_ok=True)
                save.write_bytes(b"save")
                return type("Completed", (), {"returncode": 0})()
            with patch.object(module.subprocess, "run", side_effect=fake_run) as run:
                module.prepare(str(binary), str(save), str(settings), "Capivara Factorio")
                module.prepare(str(binary), str(save), str(settings), "Capivara Factorio")
            self.assertEqual(run.call_count, 1)
            payload = load(settings)
            self.assertEqual(payload["game_password"], "")
            self.assertEqual(payload["password"], "")
            self.assertEqual(payload["token"], "")

    def test_deferred_files_contain_no_real_credentials(self):
        texts = []
        for game in ("fivem", "valheim", "arksurvivalascended", "theisle"):
            path = ROOT / f"catalog/v2/games/{game}/deferred/stable.json"
            texts.append(path.read_text(encoding="utf-8"))
        combined = "\n".join(texts).lower()
        self.assertNotIn("sv_licensekey ", combined)
        self.assertNotIn("dedicatedserverclientsecret=", combined)
        theisle = load(ROOT / "catalog/v2/games/theisle/deferred/stable.json")
        self.assertEqual(theisle["version"]["config"]["steam_branch"], "evrima")


if __name__ == "__main__":
    unittest.main()
