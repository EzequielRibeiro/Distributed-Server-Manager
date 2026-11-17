#!/usr/bin/env python3
"""DayZ DLC transaction rollback on a disposable filesystem tree.

No privileged operations, no systemd, and no references to installed servers.
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "linux" / "runtime"))
from server_update_transaction import activate, prepare_staging, rollback


def evidence(path: Path) -> tuple[str, int, int, int]:
    stat = path.stat()
    return (hashlib.sha256(path.read_bytes()).hexdigest(),
            stat.st_mode & 0o777, stat.st_uid, stat.st_gid)


class DayZDlcFilesystemRollbackTest(unittest.TestCase):
    def test_rollback_restores_dlc_package_bytes_and_metadata(self):
        with tempfile.TemporaryDirectory(prefix="dsm-dayz-rollback-") as temp:
            root = Path(temp)
            target = root / "serverfiles"
            packages = {
                "nasdara": "ai_nasdara.pbo",
                "sakhal": "worlds_sakhal.ebo",
            }
            for dlc, name in packages.items():
                folder = target / dlc / "addons"
                folder.mkdir(parents=True)
                package = folder / name
                package.write_bytes(("old-" + dlc).encode())
                package.chmod(0o640)
            (target / "DayZServer").write_bytes(b"old-server")
            original = {dlc: evidence(target / dlc / "addons" / name)
                        for dlc, name in packages.items()}
            stage = prepare_staging(target)
            for dlc, name in packages.items():
                staged = stage / dlc / "addons" / name
                staged.write_bytes(("new-" + dlc).encode())
                staged.chmod(0o644)
            (stage / "DayZServer").write_bytes(b"new-server")
            previous = activate(target, stage)
            self.assertEqual((target / "DayZServer").read_bytes(), b"new-server")
            self.assertTrue(rollback(target, previous))
            self.assertEqual((target / "DayZServer").read_bytes(), b"old-server")
            self.assertEqual(
                {dlc: evidence(target / dlc / "addons" / name)
                 for dlc, name in packages.items()}, original
            )

    def test_unavailable_previous_tree_does_not_claim_rollback_success(self):
        with tempfile.TemporaryDirectory(prefix="dsm-dayz-rollback-") as temp:
            root = Path(temp)
            target = root / "serverfiles"
            target.mkdir()
            package = target / "DayZServer"
            package.write_bytes(b"new-server")
            self.assertFalse(rollback(target, root / "missing-previous"))
            self.assertEqual(package.read_bytes(), b"new-server")


if __name__ == "__main__":
    unittest.main()
