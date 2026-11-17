"""Resource-safe, read-only preflight tests before real restored ATM11 world boot."""
from __future__ import annotations

import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from minecraft_restored_world_boot_preflight import (
    GIB, MIN_AVAILABLE_MEMORY_GIB, preflight, _is_inside
)

IID = "cli-000001-minecraft-005"


class RestoredWorldBootPreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsm-1013-world-preflight-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sandbox = self.root / "disposable-test"
        self.sandbox.mkdir()
        self.backup_id = str(uuid4())
        self.backup = self.root / (self.backup_id + ".tar.gz")
        self.archive()

    def archive(self, *, game="minecraft", runtime="minecraft.java.neoforge",
                source=IID, backup_id=None):
        manifest = {
            "kind": "CapivaraInstanceBackup",
            "backup_format": "capivara-instance",
            "backup_id": backup_id or self.backup_id,
            "game_id": game,
            "runtime_id": runtime,
            "source_instance": source,
        }
        raw = json.dumps(manifest).encode()
        with tarfile.open(self.backup, "w:gz") as t:
            member = tarfile.TarInfo(".capivara-backup-manifest.json")
            member.size = len(raw)
            t.addfile(member, io.BytesIO(raw))
            data = b"minecraft-level-data" * 100
            member = tarfile.TarInfo("world/level.dat")
            member.size = len(data)
            t.addfile(member, io.BytesIO(data))

    def probe(self, **kwargs):
        args = {
            "instance_id": IID, "backup_id": self.backup_id,
            "meminfo": "MemAvailable: 18000000 kB\n",
            "disk_free_bytes": 48 * GIB,
            "cpu_count": 8, "load_one": 1.0,
            "port_free": True, "systemd_available": True,
        }
        args.update(kwargs)
        return preflight(self.backup, self.sandbox, **args)

    def test_all_gates_pass_without_touching_files(self):
        before = [(p.name, p.stat().st_size) for p in self.root.iterdir()]
        proof = self.probe()
        self.assertEqual(proof["status"], "preflight_pass")
        self.assertFalse(proof["archive_sha256_verified_by_this_preflight"])
        self.assertEqual([], proof["reasons"])
        self.assertEqual("read_only_no_boot_no_restore", proof["scope"])
        self.assertEqual(before, [(p.name, p.stat().st_size) for p in self.root.iterdir()])

    def test_current_horizon_memory_headroom_refuses_boot(self):
        proof = self.probe(meminfo="MemAvailable: 6040000 kB\n")
        self.assertEqual(proof["status"], "blocked")
        self.assertIn("insufficient_available_memory", proof["reasons"])
        self.assertEqual(proof["next_step"], "do_not_boot_on_this_host")

    def test_insufficient_disk_busy_host_port_and_systemd_refuse(self):
        proof = self.probe(disk_free_bytes=1 * GIB, cpu_count=4,
                           load_one=3.5, port_free=False, systemd_available=False)
        self.assertEqual(proof["status"], "blocked")
        self.assertEqual(
            proof["reasons"],
            ["insufficient_disposable_disk", "host_too_busy",
             "sandbox_loopback_port_in_use", "systemd_unavailable"],
        )

    def test_threshold_requires_at_least_12_gib_free_memory(self):
        boundary = MIN_AVAILABLE_MEMORY_GIB * GIB // 1024
        self.assertEqual(
            self.probe(meminfo=f"MemAvailable: {boundary} kB\n")["status"],
            "preflight_pass",
        )
        self.assertEqual(
            self.probe(meminfo=f"MemAvailable: {boundary - 1} kB\n")["status"],
            "blocked",
        )

    def test_invalid_manifest_backup_id_and_game_fail_closed(self):
        for values in (
            {"game": "dayz"}, {"runtime": "minecraft.java.vanilla"},
            {"source": "another-instance"}, {"backup_id": str(uuid4())},
        ):
            with self.subTest(values=values):
                self.archive(**values)
                with self.assertRaisesRegex(ValueError, "identity"):
                    self.probe()
        self.archive()
        with self.assertRaisesRegex(ValueError, "backup identifier"):
            self.probe(backup_id="../danger")
        with self.assertRaisesRegex(ValueError, "source instance"):
            self.probe(instance_id="../danger")

    def test_symlinked_sources_and_sandbox_denied(self):
        alias = self.root / "backup-link.tar.gz"
        alias.symlink_to(self.backup)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            preflight(alias, self.sandbox, instance_id=IID, backup_id=self.backup_id)
        folder_alias = self.root / "folder-link"
        folder_alias.symlink_to(self.sandbox, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            preflight(self.backup, folder_alias, instance_id=IID, backup_id=self.backup_id)
        self.assertTrue(_is_inside(Path("/opt/dsm/runtime/test"), Path("/opt/dsm/runtime")))
        self.assertFalse(_is_inside(self.sandbox, Path("/opt/dsm/runtime")))

    def test_bad_meminfo_and_port_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "MemAvailable"):
            self.probe(meminfo="MemFree: 50 kB\n")
        with self.assertRaisesRegex(ValueError, "unprivileged"):
            self.probe(port=22)

    def test_real_loopback_port_occupancy_check_is_read_only(self):
        with socket.socket() as listening:
            listening.bind(("127.0.0.1", 0))
            port = listening.getsockname()[1]
            listening.listen(1)
            proof = self.probe(port=port, port_free=None)
            self.assertEqual(proof["status"], "blocked")
            self.assertIn("sandbox_loopback_port_in_use", proof["reasons"])

    def test_cli_reports_blocked_and_never_writes(self):
        with socket.socket() as listening:
            listening.bind(("127.0.0.1", 0))
            port = listening.getsockname()[1]
            listening.listen(1)
            before = tuple(sorted(p.name for p in self.root.iterdir()))
            cli = ROOT / "scripts/minecraft_restored_world_boot_preflight.py"
            result = subprocess.run(
                [sys.executable, str(cli), "--archive", str(self.backup),
                 "--sandbox-parent", str(self.sandbox), "--instance-id", IID,
                 "--backup-id", self.backup_id, "--port", str(port)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 2)
            proof = json.loads(result.stdout)
            self.assertIn(proof["status"], ("blocked", "blocked_invalid_evidence"))
            self.assertEqual(before, tuple(sorted(p.name for p in self.root.iterdir())))


if __name__ == "__main__":
    unittest.main()
