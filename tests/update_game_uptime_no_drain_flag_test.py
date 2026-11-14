"""#928: unsupported no-drain option must fail before root/host actions."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NoDrainFlagFailClosedTests(unittest.TestCase):
    def test_unsupported_flag_rejected_without_touching_host(self):
        result = subprocess.run(
            ["bash", str(ROOT / "update.sh"), "--no-drain", "/tmp/dsm928-nonexistent"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("not yet homologated", result.stderr)

    def test_no_drain_rejected_with_automatic_and_backup_bypass_flags(self):
        for args in (
            ["--yes", "--no-drain", "--no-backup", "/tmp/dsm928-nonexistent"],
            ["--no-backup", "--yes", "--no-drain", "/tmp/dsm928-nonexistent"],
            ["/tmp/dsm928-nonexistent", "--no-drain", "--yes"],
        ):
            with self.subTest(args=args):
                result = subprocess.run(
                    ["bash", str(ROOT / "update.sh"), *args],
                    cwd=str(ROOT), capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("not yet homologated", result.stderr)

    def test_normal_help_still_available(self):
        result = subprocess.run(
            ["bash", str(ROOT / "update.sh"), "--help"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--no-backup", result.stdout)


if __name__ == "__main__":
    unittest.main()
