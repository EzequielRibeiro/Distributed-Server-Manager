"""Fail-closed path checks for privileged Minecraft Server Pack migration."""
import importlib.util
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "agents/linux/privileged/materialize_instance.py"
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))


class ServerPackMigrationRootTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Other platform tests may have already imported a Windows module with
        # the same basename. Load the Linux implementation for this helper.
        linux_policy_path = ROOT / "agents/linux/runtime/catalog_runtime_policy.py"
        policy_spec = importlib.util.spec_from_file_location(
            "capivara_linux_catalog_runtime_policy_test", linux_policy_path
        )
        linux_policy = importlib.util.module_from_spec(policy_spec)
        policy_spec.loader.exec_module(linux_policy)
        spec = importlib.util.spec_from_file_location("capivara_serverpack_privileged_helper", HELPER)
        cls.helper = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"catalog_runtime_policy": linux_policy}):
            spec.loader.exec_module(cls.helper)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pool = Path(self.tmp.name) / "pool"
        self.pool.mkdir()
        self.instance = self.pool / "minecraft-005"
        self.instance.mkdir()
        (self.instance / "runtime").mkdir()
        self.spec = {
            "instance_id": "minecraft-005",
            "game_id": "minecraft",
            "environment_id": "minecraft.java.neoforge",
            "instance_state_root": str(self.instance),
            "working_directory": str(self.instance / "runtime"),
        }
        self.mock_pool = patch.object(self.helper, "_instance_storage_root", return_value=self.pool)
        self.mock_pool.start()
        self.addCleanup(self.mock_pool.stop)

    def _fixture_runtime(self, root, version, marker):
        root.mkdir()
        libraries = root / "libraries/net/neoforged/neoforge" / version
        libraries.mkdir(parents=True)
        arguments = libraries / "unix_args.txt"
        arguments.write_bytes(b"--loader " + version.encode() + b"\n")
        (root / "capivara-launch.args").write_bytes(arguments.read_bytes())
        (root / "user_jvm_args.txt").write_text("-Xmx1G\n")
        (root / "world").mkdir()
        (root / "world/level.dat").write_bytes(marker)

    def _fixture_swap(self):
        (self.instance / "runtime").rmdir()
        self._fixture_runtime(self.instance / "runtime", "26.1.2.94", b"ORIGINAL")
        self._fixture_runtime(self.instance / "runtime.migration-stage", "26.1.2.109", b"CANDIDATE")
        self.helper._serverpack_swap_phase(
            self.spec, {}, phase="prepare", migration_plan_sha256="b" * 64,
            target_loader_version="26.1.2.109",
            backup={"backup_id": "backup-isolated", "sha256": "d" * 64,
                    "size_bytes": 1234, "integrity_verified": True},
        )

    def test_privileged_swap_and_recovery_on_disposable_fixture(self):
        self._fixture_swap()
        result = self.helper._serverpack_swap_phase(self.spec, {}, phase="switch")
        self.assertEqual(result["phase"], "swapped")
        self.assertEqual((self.instance / "runtime/world/level.dat").read_bytes(), b"CANDIDATE")
        restored = self.helper._serverpack_swap_phase(self.spec, {}, phase="recover")
        self.assertEqual(restored["status"], "recovered")
        self.assertEqual((self.instance / "runtime/world/level.dat").read_bytes(), b"ORIGINAL")
        self.assertEqual((self.instance / "runtime.migration-failed/world/level.dat").read_bytes(), b"CANDIDATE")

    def test_privileged_commit_after_fresh_readiness_on_disposable_fixture(self):
        self._fixture_swap()
        candidate = self.instance / "runtime.migration-stage"
        # The journal was prepared before adding mods, so prepare this fixture again.
        import minecraft_serverpack_migration_swap as swap
        (self.instance / ".dsm/minecraft-serverpack-migration.json").unlink()
        (candidate / "mods").mkdir()
        (candidate / "mods/example.jar").write_bytes(b"mod")
        self.helper._serverpack_swap_phase(
            self.spec, {}, phase="prepare", migration_plan_sha256="b" * 64,
            target_loader_version="26.1.2.109",
            backup={"backup_id": "backup-isolated", "sha256": "d" * 64,
                    "size_bytes": 1234, "integrity_verified": True},
        )
        self.helper._serverpack_swap_phase(self.spec, {}, phase="switch")
        active = self.instance / "runtime"
        logs = active / "logs"
        logs.mkdir(exist_ok=True)
        (logs / "latest.log").write_text("[Server thread/INFO]: Done (isolated startup)\n")
        result = self.helper._serverpack_swap_phase(
            self.spec, {}, phase="commit",
            readiness_evidence={"passed": True, "migration_plan_sha256": "b" * 64,
                                "target_loader_version": "26.1.2.109",
                                "serverpack_mod_count": 1},
        )
        self.assertEqual(result["status"], "committed")
        self.assertEqual((active / "world/level.dat").read_bytes(), b"CANDIDATE")
        self.assertEqual((self.instance / "runtime.migration-rollback/world/level.dat").read_bytes(), b"ORIGINAL")
        with self.assertRaisesRegex(swap.MinecraftServerPackMigrationSwapError, "cannot be silently recovered"):
            self.helper._serverpack_swap_phase(self.spec, {}, phase="recover")

    def test_privileged_recovery_after_interrupted_first_rename(self):
        import minecraft_serverpack_migration_swap as swap
        self._fixture_swap()
        original_replace = swap.os.replace
        interrupted = {"once": False}
        def interrupt_after_first_rename(src, dst):
            if (Path(src) == self.instance / "runtime.migration-stage"
                    and not interrupted["once"]):
                interrupted["once"] = True
                raise OSError("simulated interruption before candidate activation")
            return original_replace(src, dst)
        with patch.object(swap.os, "replace", side_effect=interrupt_after_first_rename):
            with self.assertRaisesRegex(OSError, "simulated interruption"):
                self.helper._serverpack_swap_phase(self.spec, {}, phase="switch")
        self.assertFalse((self.instance / "runtime").exists())
        recovery = self.helper._serverpack_swap_phase(self.spec, {}, phase="recover")
        self.assertEqual(recovery["status"], "recovered")
        self.assertEqual((self.instance / "runtime/world/level.dat").read_bytes(), b"ORIGINAL")

    def test_inactive_unit_required_for_privileged_mutations(self):
        from types import SimpleNamespace
        with patch.object(self.helper.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout="LoadState=loaded\nActiveState=inactive\n")) as run:
            self.helper._serverpack_require_inactive(self.spec["instance_id"])
            self.assertIn("capivara-instance-minecraft-005.service", run.call_args.args[0])
        with patch.object(self.helper.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout="LoadState=loaded\nActiveState=active\n")):
            with self.assertRaisesRegex(RuntimeError, "inactive loaded"):
                self.helper._serverpack_require_inactive(self.spec["instance_id"])
        with patch.object(self.helper.subprocess, "run", return_value=SimpleNamespace(
                returncode=0, stdout="LoadState=not-found\nActiveState=inactive\n")):
            with self.assertRaisesRegex(RuntimeError, "inactive loaded"):
                self.helper._serverpack_require_inactive(self.spec["instance_id"])

    def test_unit_state_check_fails_closed_on_systemd_error(self):
        from types import SimpleNamespace
        with patch.object(self.helper.subprocess, "run", return_value=SimpleNamespace(
                returncode=1, stdout="", stderr="offline")):
            with self.assertRaisesRegex(RuntimeError, "cannot verify"):
                self.helper._serverpack_require_inactive(self.spec["instance_id"])

    def test_valid_instance_root(self):
        self.assertEqual(self.helper._serverpack_migration_root(self.spec, {}), self.instance)

    def test_fixed_migration_paths(self):
        paths = self.helper._serverpack_migration_paths(self.spec, {})
        self.assertEqual(paths["stage"], self.instance / "runtime.migration-stage")
        self.assertEqual(paths["rollback"], self.instance / "runtime.migration-rollback")
        self.assertEqual(paths["journal"], self.instance / ".dsm" / "minecraft-serverpack-migration.json")

    def test_rejects_symlink_control(self):
        other = self.pool / "external-control"
        other.mkdir()
        (self.instance / ".dsm").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "control directory is unsafe"):
            self.helper._serverpack_migration_paths(self.spec, {})

    def test_rejects_symlink_candidate(self):
        other = self.pool / "external-candidate"
        other.mkdir()
        (self.instance / "runtime.migration-stage").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "stage directory is unsafe"):
            self.helper._serverpack_migration_paths(self.spec, {})

    def test_rejects_symlink_journal(self):
        control = self.instance / ".dsm"
        control.mkdir()
        external = self.pool / "external-journal"
        external.write_text("test")
        (control / "minecraft-serverpack-migration.json").symlink_to(external)
        with self.assertRaisesRegex(RuntimeError, "journal path is unsafe"):
            self.helper._serverpack_migration_paths(self.spec, {})

    def test_build_rejects_missing_input_stage(self):
        with self.assertRaisesRegex(RuntimeError, "input stage is missing"):
            self.helper._serverpack_build_candidate(
                self.spec, {}, loader_seed_value="/tmp/seed", target_loader_version="26.1.2.109"
            )
        self.assertFalse((self.instance / "runtime.migration-stage").exists())

    def test_build_rejects_input_stage_symlink(self):
        control = self.instance / ".dsm"
        control.mkdir()
        external = self.pool / "external-stage"
        external.mkdir()
        (control / "pr855-serverpack-stage").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "input stage is missing or unsafe"):
            self.helper._serverpack_build_candidate(
                self.spec, {}, loader_seed_value="/tmp/seed", target_loader_version="26.1.2.109"
            )
        self.assertFalse((self.instance / "runtime.migration-stage").exists())

    def test_prepare_rejects_existing_journal_without_deletion(self):
        control = self.instance / ".dsm"
        control.mkdir()
        journal = control / "minecraft-serverpack-migration.json"
        journal.write_text("preserve")
        with self.assertRaisesRegex(RuntimeError, "journal already exists"):
            self.helper._serverpack_prepare_inputs(
                self.spec, {}, migration_value={}, selection={}
            )
        self.assertEqual(journal.read_text(), "preserve")

    def test_prepare_rejects_occupied_candidate_without_deletion(self):
        candidate = self.instance / "runtime.migration-stage"
        candidate.mkdir()
        marker = candidate / "world"
        marker.write_text("preserve")
        with self.assertRaisesRegex(RuntimeError, "destination already occupied"):
            self.helper._serverpack_prepare_inputs(
                self.spec, {}, migration_value={}, selection={}
            )
        self.assertEqual(marker.read_text(), "preserve")

    def test_commit_denied_without_readiness_evidence(self):
        with self.assertRaisesRegex(RuntimeError, "requires successful readiness evidence"):
            self.helper._serverpack_swap_phase(self.spec, {}, phase="commit")

    def test_commit_denied_when_readiness_is_false(self):
        with self.assertRaisesRegex(RuntimeError, "requires successful readiness evidence"):
            self.helper._serverpack_swap_phase(
                self.spec, {}, phase="commit", readiness_evidence={"passed": False}
            )

    def test_commit_requires_new_log_output_after_root_checkpoint(self):
        import minecraft_serverpack_migration_swap as swap
        active = self.instance / "runtime"
        logs = active / "logs"
        logs.mkdir()
        log = logs / "latest.log"
        log.write_text("[Server thread/INFO]: Done (old startup)\n")
        mods = active / "mods"
        mods.mkdir()
        (mods / "example.jar").write_bytes(b"mod")
        evidence = {"passed": True, "migration_plan_sha256": "a" * 64,
                    "target_loader_version": "26.1.2.109", "serverpack_mod_count": 1}
        baseline = {"inode": log.stat().st_ino, "size": log.stat().st_size}
        journal = {"phase": "swapped", "readiness_checkpoint_recorded": True,
                   "readiness_log_baseline": baseline,
                   "migration_plan_sha256": evidence["migration_plan_sha256"],
                   "target_loader_version": evidence["target_loader_version"]}
        with patch.object(swap, "_paths", return_value={}), \
             patch.object(swap, "_read", return_value=journal), \
             patch.object(swap, "commit", return_value={"status": "committed"}) as commit:
            with self.assertRaisesRegex(RuntimeError, "no fresh readiness log"):
                self.helper._serverpack_swap_phase(
                    self.spec, {}, phase="commit", readiness_evidence=evidence)
            commit.assert_not_called()
            with log.open("a") as stream:
                stream.write("[Server thread/INFO]: Done (new startup)\n")
            self.assertEqual(self.helper._serverpack_swap_phase(
                self.spec, {}, phase="commit", readiness_evidence=evidence)["status"], "committed")
            commit.assert_called_once()

    def test_commit_denied_when_root_checkpoint_is_missing(self):
        import minecraft_serverpack_migration_swap as swap
        evidence = {"passed": True, "migration_plan_sha256": "a" * 64,
                    "target_loader_version": "26.1.2.109", "serverpack_mod_count": 1}
        journal = {"phase": "swapped", "migration_plan_sha256": "a" * 64,
                   "target_loader_version": "26.1.2.109"}
        with patch.object(swap, "_paths", return_value={}), \
             patch.object(swap, "_read", return_value=journal), \
             patch.object(swap, "commit") as commit:
            with self.assertRaisesRegex(RuntimeError, "checkpoint is missing"):
                self.helper._serverpack_swap_phase(
                    self.spec, {}, phase="commit", readiness_evidence=evidence)
            commit.assert_not_called()

    def test_commit_denied_when_plan_differs_from_checkpoint(self):
        import minecraft_serverpack_migration_swap as swap
        evidence = {"passed": True, "migration_plan_sha256": "b" * 64,
                    "target_loader_version": "26.1.2.109", "serverpack_mod_count": 1}
        journal = {"phase": "swapped", "migration_plan_sha256": "a" * 64,
                   "target_loader_version": "26.1.2.109",
                   "readiness_checkpoint_recorded": True}
        with patch.object(swap, "_paths", return_value={}), \
             patch.object(swap, "_read", return_value=journal), \
             patch.object(swap, "commit") as commit:
            with self.assertRaisesRegex(RuntimeError, "differs from migration checkpoint"):
                self.helper._serverpack_swap_phase(
                    self.spec, {}, phase="commit", readiness_evidence=evidence)
            commit.assert_not_called()

    def test_recovery_allows_temporarily_missing_runtime(self):
        (self.instance / "runtime").rmdir()
        self.assertEqual(
            self.helper._serverpack_migration_paths(self.spec, {}, allow_missing_active=True)["root"],
            self.instance,
        )
        with self.assertRaisesRegex(RuntimeError, "active runtime is unsafe"):
            self.helper._serverpack_migration_paths(self.spec, {})

    def test_recovery_still_rejects_symlink_runtime(self):
        (self.instance / "runtime").rmdir()
        external = self.pool / "outside"
        external.mkdir()
        (self.instance / "runtime").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "active runtime is unsafe"):
            self.helper._serverpack_migration_paths(self.spec, {}, allow_missing_active=True)

    def test_rejects_other_instance(self):
        self.spec["instance_state_root"] = str(self.pool / "minecraft-006")
        with self.assertRaisesRegex(RuntimeError, "storage policy"):
            self.helper._serverpack_migration_root(self.spec, {})

    def test_rejects_wrong_game(self):
        self.spec["game_id"] = "dayz"
        with self.assertRaisesRegex(RuntimeError, "Minecraft"):
            self.helper._serverpack_migration_root(self.spec, {})

    def test_rejects_wrong_working_directory(self):
        self.spec["working_directory"] = str(self.pool / "minecraft-006" / "runtime")
        with self.assertRaisesRegex(RuntimeError, "working directory"):
            self.helper._serverpack_migration_root(self.spec, {})

    def test_rejects_symlink_runtime(self):
        (self.instance / "runtime").rmdir()
        other = self.pool / "other-runtime"
        other.mkdir()
        (self.instance / "runtime").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "active runtime is unsafe"):
            self.helper._serverpack_migration_root(self.spec, {})

    def test_rejects_symlink_root(self):
        other = self.pool / "elsewhere"
        other.mkdir()
        (self.instance / "runtime").rmdir()
        self.instance.rmdir()
        self.instance.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "unsafe"):
            self.helper._serverpack_migration_root(self.spec, {})


if __name__ == "__main__":
    unittest.main()
