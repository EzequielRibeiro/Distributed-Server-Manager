#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BaselineReleaseUpgradeContractTest(unittest.TestCase):
    def test_release_builder_preserves_canonical_process_guard(self) -> None:
        text = (ROOT / "release" / "build_release.sh").read_text(encoding="utf-8")
        self.assertNotIn("fully reconciled ledger is already compatible", text)
        self.assertIn("accepted checksum mismatch without pending upgrade", text)
        self.assertIn("rejected registered v12/v13 pending upgrades", text)

    def test_release_package_builds_with_guard_regression_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                ["bash", str(ROOT / "release" / "build_release.sh"), "HEAD", tmp],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            version = (ROOT / "version").read_text(encoding="utf-8").strip()
            self.assertTrue((Path(tmp) / f"capivara-dsm-{version}.tar.gz").is_file())


if __name__ == "__main__":
    unittest.main()
