"""Read-only hybrid Steam version probe regression tests."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXECUTOR = ROOT / "dashboard/workers/hybrid_game_data_executor.py"


class HybridVerifyReadOnlyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.target = self.base / "game"
        self.target.mkdir()
        (self.target / "steamapps").mkdir()
        (self.target / "steamapps/appmanifest_223350.acf").write_text('"buildid" "1001"\n')
        self.root = self.base / "root"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        steam = self.bin / "steamcmd"
        steam.write_text("#!/bin/sh\ncase \"$*\" in *+app_update*|*+force_install_dir*) exit 93;; esac\nprintf '%s\\n' '\"branches\"' '{' '\"public\"' '{' '\"buildid\" \"1002\"' '}' '}'\n")
        steam.chmod(0o755)
        self.marker = self.root / "installer-was-called"
        installer = self.root / "installer/install_selection.sh"
        installer.parent.mkdir(parents=True)
        installer.write_text("#!/bin/sh\ntouch " + str(self.marker) + "\nexit 99\n")
        installer.chmod(0o755)

    def run_probe(self, *, provider="steam", package_id=223350, branch="public"):
        request = self.base / "request.json"
        result = self.base / "result.json"
        request.write_text(json.dumps({"job_id": "probe-test", "action": "verify", "selection": {
            "game": "dayz", "provider": provider, "install": {"package_id": package_id, "branch": branch},
            "install_dir": str(self.target),
        }}))
        env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
                   HOME=str(self.base / "home"), CAPIVARA_STEAM_HOME=str(self.base / "home"),
                   CAPIVARA_AGENT_STATE_DIR=str(self.base / "agent-state"),
                   DSM_TEST_PROBE_HOME_FILE=str(self.base / "probe-home.txt"))
        p = subprocess.run([sys.executable, str(EXECUTOR), str(self.root), str(request), str(result)],
                           env=env, capture_output=True, text=True, timeout=15)
        self.assertFalse(self.marker.exists())
        return p, json.loads(result.read_text())

    def test_update_available(self):
        p, result = self.run_probe()
        self.assertEqual(p.returncode, 0, result)
        self.assertEqual(result["update_status"]["installed_version"], "1001")
        self.assertEqual(result["update_status"]["available_version"], "1002")
        self.assertEqual(result["update_status"]["state"], "update_available")

    def test_anonymous_steamcmd_probe_uses_private_home_not_authenticated_session(self):
        authenticated_home = self.base / "home"
        authenticated_config = authenticated_home / ".local/share/Steam/config/config.vdf"
        authenticated_config.parent.mkdir(parents=True)
        authenticated_config.write_text("FAKE_AUTHENTICATED_TEST_DATA")
        authenticated_config.chmod(0o600)
        self.bin.joinpath("steamcmd").write_text(
            '#!/bin/sh\nprintf "%s\\n" "$HOME" > "$DSM_TEST_PROBE_HOME_FILE"\n'
            "printf '%s\\n' '\"branches\"' '{' '\"public\"' '{' '\"buildid\" \"1002\"' '}' '}'\n"
        )
        self.bin.joinpath("steamcmd").chmod(0o755)
        before = authenticated_config.stat()
        p, result = self.run_probe()
        self.assertEqual(p.returncode, 0, result)
        anonymous_home = Path((self.base / "probe-home.txt").read_text().strip())
        self.assertEqual(anonymous_home, self.base / "agent-state/steam-anonymous-metadata-home")
        self.assertEqual(stat.S_IMODE(anonymous_home.stat().st_mode), 0o700)
        self.assertNotEqual(anonymous_home, authenticated_home)
        after = authenticated_config.stat()
        self.assertEqual((before.st_ino, before.st_size, before.st_mtime_ns),
                         (after.st_ino, after.st_size, after.st_mtime_ns))
        self.assertEqual(authenticated_config.read_text(), "FAKE_AUTHENTICATED_TEST_DATA")

    def test_up_to_date(self):
        (self.target / "steamapps/appmanifest_223350.acf").write_text('"buildid" "1002"\n')
        p, result = self.run_probe()
        self.assertEqual(p.returncode, 0, result)
        self.assertEqual(result["update_status"]["state"], "up_to_date")

    def test_missing_manifest_is_unknown(self):
        (self.target / "steamapps/appmanifest_223350.acf").unlink()
        p, result = self.run_probe()
        self.assertEqual(p.returncode, 0, result)
        self.assertEqual(result["update_status"]["state"], "unknown")

    def test_global_manifest_not_used(self):
        (self.target / "steamapps/appmanifest_223350.acf").unlink()
        global_manifest = self.base / "home/.local/share/Steam/steamapps"
        global_manifest.mkdir(parents=True)
        (global_manifest / "appmanifest_223350.acf").write_text('"buildid" "1002"\\n')
        p, result = self.run_probe()
        self.assertEqual(p.returncode, 0, result)
        self.assertEqual(result["update_status"]["state"], "unknown")

    def test_invalid_app_id_fails_closed(self):
        p, result = self.run_probe(package_id="223350;touch /tmp/unsafe")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(result["error"], "read_only_version_probe_invalid_app_id")

    def test_unsupported_provider_fails_closed(self):
        p, result = self.run_probe(provider="direct")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(result["error"], "read_only_version_probe_unsupported_provider")

    def test_unavailable_branch_fails_closed(self):
        p, result = self.run_probe(branch="private")
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(result["error"], "read_only_version_probe_metadata_unavailable")


if __name__ == "__main__":
    unittest.main()
