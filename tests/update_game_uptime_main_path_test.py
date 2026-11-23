"""Full update.sh main() order in an owner-marked disposable filesystem only."""
from __future__ import annotations

import subprocess
import json
from importlib.machinery import SourceFileLoader
import importlib.util
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests/fixtures/update_928_main_path_rehearsal.sh"
UPDATER = ROOT / "update.sh"

from update_game_uptime_real_update_functions_test import create_tiny_release_fixture


def fixture_signer():
    path = ROOT / "update-manager/game-uptime-fixture-attestation.py"
    loader = SourceFileLoader("dsm928_test_package_signer", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    helper = importlib.util.module_from_spec(spec)
    loader.exec_module(helper)
    return helper


def main_rehearsal(workspace: Path, mode="success") -> subprocess.CompletedProcess:
    return subprocess.run(
        ("bash", str(HARNESS), str(workspace), str(UPDATER), mode),
        capture_output=True, text=True, check=False, timeout=35,
    )


class MainPathRehearsalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dsm928-main-path-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        create_tiny_release_fixture(self.root)
        # The real updater's semantic-version gate needs valid version strings.
        (self.root/"installed/version").write_text("2.0.998")
        (self.root/"new-payload/version").write_text("2.0.999")
        self.installed = self.root/"installed"
        self.world = self.installed/"runtime/hybrid-instance-storage/minecraft005/world/level.dat"
        self.upload = self.installed/"runtime/artifact-transfers/job-001/upload.part"

    def prepare_no_drain_fixture(self):
        # Keep the checked-out source's actual backup/apply/rollback file
        # routines, but ensure every release change is compatible with the
        # STRICT control-plane-only classifier. Runtime/database state is
        # identical, whereas the dashboard and version are changed.
        for tree in (self.root / "installed", self.root / "new-payload"):
            supervisor = tree / "agents/linux/runtime/console_supervisor.py"
            supervisor.parent.mkdir(parents=True, exist_ok=True)
            supervisor.write_text("stable supervisor fixture\\n")
        target_db = self.root / "new-payload/data/database.txt"
        target_db.parent.mkdir(parents=True, exist_ok=True)
        target_db.write_bytes((self.installed / "data/database.txt").read_bytes())
        (self.installed / "version").write_text("2.0.998-fixture")
        (self.root / "new-payload/version").write_text("2.0.999-fixture")
        fixture_signer().seal_test_fixture(self.root)

    def test_disposable_no_drain_actual_main_success_preserves_data_and_never_drains(self):
        self.prepare_no_drain_fixture()
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 0,
                         outcome.stderr[-3000:] + outcome.stdout[-1900:])
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.999-fixture")
        receipt = json.loads(
            (self.root / "dsm928-composite-journal/game-uptime-transaction.json").read_text())
        self.assertTrue(receipt["strict_inventory"])
        self.assertEqual(receipt["status"], "verified")
        self.assertEqual(len(receipt["original_units"]), 2)
        self.assertFalse(receipt["live_no_drain_authorized"])
        self.assertIn("DSM928MainDisposableNoDrainRehearsal", outcome.stdout)
        self.assertTrue(json.loads(outcome.stdout.strip().splitlines()[-1])["fixture_package_attested"])
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual(self.upload.read_bytes(), b"in-flight-upload-private-test")
        self.assertEqual(len(list((self.root / "backups").glob("*.tar.gz"))), 1)
        self.assertFalse((self.root / "steps").exists(), "never call stop/start service hooks")

    def test_disposable_no_drain_main_injected_failure_rolls_back_without_draining(self):
        self.prepare_no_drain_fixture()
        outcome = main_rehearsal(self.root, "no_drain_fail_after_apply")
        self.assertEqual(outcome.returncode, 2, outcome.stderr[-2500:])
        self.assertIn("EXPECTED_DISPOSABLE_ROLLBACK_CONFIRMED", outcome.stdout)
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.998-fixture")
        receipt = json.loads(
            (self.root / "dsm928-composite-journal/game-uptime-transaction.json").read_text())
        self.assertEqual(receipt["status"], "rolled_back")
        self.assertTrue(receipt["strict_inventory"])
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual(self.upload.read_bytes(), b"in-flight-upload-private-test")
        self.assertFalse((self.root / "steps").exists())

    def test_disposable_no_drain_main_rejects_new_game_before_any_backup(self):
        self.prepare_no_drain_fixture()
        (self.root / "fixture-add-game-during-handoff").write_text("new game")
        outcome = main_rehearsal(self.root, "no_drain_drift")
        self.assertEqual(outcome.returncode, 2, outcome.stdout[-800:] + outcome.stderr[-1300:])
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.998-fixture")
        self.assertFalse((self.root / "dsm928-composite-journal").exists())
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])
        self.assertFalse((self.root / "steps").exists())

    def test_disposable_no_drain_main_rejects_unclassified_schema_change(self):
        self.prepare_no_drain_fixture()
        unexpected = self.root / "new-payload/database/migrations/099.sql"
        unexpected.parent.mkdir(parents=True, exist_ok=True)
        unexpected.write_text("ALTER TABLE x")
        # A newly signed package is still blocked by the independent impact
        # classifier; HMAC verification must not override release safety.
        fixture_signer().seal_test_fixture(self.root)
        outcome = main_rehearsal(self.root, "no_drain_unknown_file")
        self.assertEqual(outcome.returncode, 2, outcome.stderr[-1300:])
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.998-fixture")
        self.assertFalse((self.root / "dsm928-composite-journal").exists())
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_disposable_no_drain_unsigned_payload_blocks_before_backup(self):
        self.prepare_no_drain_fixture()
        (self.root / ".dsm928-fixture-package-seal.json").unlink()
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 2)
        self.assertEqual((self.installed / "version").read_text(), "2.0.998-fixture")
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])
        self.assertFalse((self.root / "dsm928-composite-journal").exists())

    def test_disposable_no_drain_modified_signed_payload_blocks_before_backup(self):
        self.prepare_no_drain_fixture()
        (self.root / "new-payload/dashboard/web/presentation.js").write_text("injected")
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 2)
        self.assertEqual((self.installed / "version").read_text(), "2.0.998-fixture")
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_disposable_no_drain_forged_mac_blocks_before_backup(self):
        self.prepare_no_drain_fixture()
        path = self.root / ".dsm928-fixture-package-seal.json"
        forged = json.loads(path.read_text())
        forged["hmac_sha256"] = "f" * 64
        path.write_text(json.dumps(forged))
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 2)
        self.assertFalse((self.root / "dsm928-composite-journal").exists())
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_disposable_no_drain_key_symlink_blocks_before_backup(self):
        self.prepare_no_drain_fixture()
        key = self.root / ".dsm928-fixture-signer.key"
        other = self.root / "different.key"
        other.write_bytes(key.read_bytes())
        key.unlink()
        key.symlink_to(other)
        outcome = main_rehearsal(self.root, "no_drain_success")
        self.assertEqual(outcome.returncode, 2)
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_disposable_no_drain_main_refuses_without_explicit_fixture_opt_in(self):
        self.prepare_no_drain_fixture()
        outcome = main_rehearsal(self.root, "no_drain_no_env")
        self.assertEqual(outcome.returncode, 2)
        self.assertEqual((self.installed / "version").read_text().strip(), "2.0.998-fixture")
        self.assertFalse((self.root / "dsm928-composite-journal").exists())
        self.assertEqual(list((self.root / "backups").glob("*.tar.gz")), [])

    def test_actual_main_path_success_preserves_world_and_checks_guard_order(self):
        outcome = main_rehearsal(self.root)
        self.assertEqual(outcome.returncode, 0, outcome.stderr[-2500:] + outcome.stdout[-1500:])
        self.assertEqual((self.installed/"version").read_text().strip(), "2.0.999")
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual(self.upload.read_bytes(), b"in-flight-upload-private-test")
        self.assertEqual((self.installed/"data/database.txt").read_text(), "db durable")
        self.assertEqual((self.installed/"runtime/hybrid-agent-state/backup-index/keep.txt").read_text(),"protected")
        self.assertEqual((self.installed/"config/dsm.conf").read_text().splitlines()[0], 'DSM_VERSION="2.0.999"')
        self.assertEqual(len(list((self.root/"backups").glob("dsm-before-update-*.tar.gz"))), 1)
        steps=(self.root/"steps").read_text().splitlines()
        self.assertEqual(steps, [
            "guard:allow-managed", "capture-games", "capture-services",
            "stop-controller", "stop-games", "guard:strict",
            "backup-database-stub", "guard:strict", "migrate-database-stub",
            "start-controller", "start-games",
        ])
        self.assertFalse((self.root/"staging").exists())
        self.assertFalse((self.root/"installed.update-preserved").exists())

    def test_actual_main_path_after_swap_failure_restores_old_product_and_world(self):
        outcome = main_rehearsal(self.root, "fail_after_apply")
        self.assertNotEqual(outcome.returncode, 0, outcome.stdout[-2500:] + outcome.stderr[-1800:])
        self.assertEqual((self.installed/"version").read_text().strip(), "2.0.998")
        self.assertEqual(self.world.read_bytes(), b"saved-world-private-test")
        self.assertEqual(self.upload.read_bytes(), b"in-flight-upload-private-test")
        self.assertEqual((self.installed/"data/database.txt").read_text(), "db durable")
        self.assertEqual((self.installed/"runtime/hybrid-agent-state/backup-index/keep.txt").read_text(),"protected")
        steps=(self.root/"steps").read_text().splitlines()
        self.assertIn("migrate-database-stub",steps)
        self.assertIn("restore-database-stub",steps)
        self.assertIn("start-controller",steps)
        self.assertIn("start-games",steps)
        self.assertNotIn("UNEXPECTED-SYSTEMCTL", steps)
        self.assertIn("stub-daemon-reload",steps)
        self.assertFalse((self.root/"installed.update-preserved").exists())

    def test_no_disposable_marker_blocks_before_real_main(self):
        (self.root/"fixture-owner").unlink()
        outcome = main_rehearsal(self.root)
        self.assertNotEqual(outcome.returncode, 0)
        self.assertEqual((self.installed/"version").read_text(), "2.0.998")
        self.assertFalse((self.root/"steps").exists())

    def test_symlinked_workspace_is_blocked_before_real_main(self):
        link = self.root.with_name(self.root.name+"-alias")
        link.symlink_to(self.root, target_is_directory=True)
        self.addCleanup(link.unlink)
        outcome = main_rehearsal(link)
        self.assertNotEqual(outcome.returncode, 0)
        self.assertEqual((self.installed/"version").read_text(), "2.0.998")
        self.assertFalse((self.root/"steps").exists())

    def test_invalid_mode_blocks_before_real_main(self):
        outcome = main_rehearsal(self.root, "production")
        self.assertNotEqual(outcome.returncode, 0)
        self.assertEqual((self.installed/"version").read_text(), "2.0.998")
        self.assertFalse((self.root/"steps").exists())


    def test_real_release_archive_applies_and_rolls_back_only_in_disposable_fixture(self):
        """#928 stage 2.1: real release artifact, real updater file swap, fake services.

        Production-affecting main() hooks remain stubbed by the existing
        owner-marked /tmp harness. The ordinary updater's drain sequence is
        verified as a BLOCKER, not advertised as no-drain compatibility.
        """
        import hashlib
        from pathlib import PurePosixPath
        import shutil
        import tarfile

        output = self.root / "release-artifact"
        output.mkdir()
        build = subprocess.run(
            ("bash", str(ROOT / "release/build_release.sh"), "HEAD", str(output)),
            text=True, capture_output=True, check=False, timeout=120,
        )
        self.assertEqual(
            build.returncode, 0, build.stderr[-1800:] + build.stdout[-900:])
        version = (ROOT / "version").read_text(encoding="utf-8").strip()
        release_name = "capivara-dsm-" + version
        archive = output / (release_name + ".tar.gz")
        checksum = output / (archive.name + ".sha256")
        manifest = json.loads(
            (output / (release_name + ".manifest.json")).read_text())
        expected_hash, filename = checksum.read_text().strip().split()
        self.assertEqual(filename, archive.name)
        self.assertEqual(
            hashlib.sha256(archive.read_bytes()).hexdigest(), expected_hash)
        commit = subprocess.run(
            ("git", "-C", str(ROOT), "rev-parse", "HEAD"),
            text=True, capture_output=True, check=True, timeout=10,
        ).stdout.strip()
        self.assertEqual(manifest["git_commit"], commit)
        self.assertEqual(manifest["version"], version)

        # Inspect the release archive before extraction; no symlinks, hardlinks,
        # absolute names, traversal, or unknown members are allowed.
        with tarfile.open(archive, "r:gz") as package:
            members = package.getmembers()
            self.assertTrue(members)
            self.assertEqual(manifest["file_count"],
                             sum(member.isfile() for member in members))
            for member in members:
                parts = PurePosixPath(member.name).parts
                self.assertTrue(parts and parts[0] == release_name
                                and ".." not in parts
                                and not member.name.startswith("/"),
                                member.name)
                self.assertTrue(member.isfile() or member.isdir(),
                                member.name)

        for mode in ("success", "fail_after_apply"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(
                    prefix="dsm928-packaged-main-") as tmp:
                workspace = Path(tmp)
                create_tiny_release_fixture(workspace)
                installed = workspace / "installed"
                # The real built release is newer than this synthetic baseline.
                (installed / "version").write_text("2.0.0")
                shutil.rmtree(workspace / "new-payload")
                expanded = workspace / "expanded"
                expanded.mkdir()
                with tarfile.open(archive, "r:gz") as package:
                    package.extractall(expanded, filter="data")
                (expanded / release_name).rename(workspace / "new-payload")

                outcome = main_rehearsal(workspace, mode)
                self.assertEqual(
                    outcome.returncode == 0, mode == "success",
                    outcome.stderr[-1600:] + outcome.stdout[-900:])
                expected_version = version if mode == "success" else "2.0.0"
                self.assertEqual(
                    (installed / "version").read_text().strip(),
                    expected_version)
                self.assertEqual(
                    (installed / "runtime/hybrid-instance-storage"
                     "/minecraft005/world/level.dat").read_bytes(),
                    b"saved-world-private-test")
                self.assertEqual(
                    (installed / "runtime/artifact-transfers"
                     "/job-001/upload.part").read_bytes(),
                    b"in-flight-upload-private-test")
                self.assertEqual(
                    (installed / "runtime/hybrid-agent-state"
                     "/backup-index/keep.txt").read_text(), "protected")
                self.assertEqual(
                    (installed / "data/database.txt").read_text(), "db durable")
                self.assertEqual(
                    len(list((workspace / "backups").glob("*.tar.gz"))), 1)
                steps = (workspace / "steps").read_text().splitlines()
                # This is the existing draining updater, not no-drain.
                self.assertIn("stop-controller", steps)
                self.assertIn("stop-games", steps)
                self.assertNotIn("UNEXPECTED-SYSTEMCTL", steps)
                self.assertFalse((workspace / "installed.update-preserved").exists())
                if mode == "success":
                    self.assertEqual(
                        json.loads((installed / "release-manifest.json")
                                   .read_text()), manifest)
                else:
                    self.assertIn("restore-database-stub", steps)


    def test_independently_signed_release_provenance_is_not_update_approval(self):
        """#928: real RSA verification, but test keys can NEVER authorize live no-drain."""
        import hashlib
        import io
        import tarfile

        loader = SourceFileLoader(
            "dsm928_signed_release_identity",
            str(ROOT / "update-manager/game-uptime-release-provenance.py"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        verifier = importlib.util.module_from_spec(spec)
        loader.exec_module(verifier)

        commit = "a" * 40
        version = "2.0.133-rc.7"
        name = "capivara-dsm-" + version
        archive = self.root / (name + ".tar.gz")
        manifest = self.root / (name + ".manifest.json")
        statement = self.root / (name + ".provenance.json")
        signature = self.root / (name + ".provenance.sig")
        private = self.root / "release-test-private.pem"
        public = self.root / "release-test-public.pem"

        release_manifest = {
            "kind": "CapivaraReleaseManifest",
            "schema_version": 1,
            "name": "capivara-dsm",
            "version": version,
            "git_commit": commit,
            "archive": archive.name,
            "file_count": 2,
        }
        manifest_bytes = (json.dumps(release_manifest, sort_keys=True,
                                     indent=2) + "\n").encode("utf-8")
        manifest.write_bytes(manifest_bytes)
        with tarfile.open(archive, "w:gz") as package:
            member = tarfile.TarInfo(name + "/release-manifest.json")
            member.size = len(manifest_bytes)
            package.addfile(member, io.BytesIO(manifest_bytes))

        # Exercise the SAME signing entrypoint used by the official
        # release workflow, with a disposable CI key outside source.
        subprocess.run(
            ("openssl", "genpkey", "-algorithm", "RSA",
             "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(private)),
            check=True, capture_output=True, timeout=30,
        )
        private.chmod(0o600)
        subprocess.run(
            ("openssl", "pkey", "-in", str(private),
             "-pubout", "-out", str(public)),
            check=True, capture_output=True, timeout=15,
        )
        signer_loader = SourceFileLoader(
            "dsm928_official_signing_entrypoint",
            str(ROOT / "release/sign_official_release.py"))
        signer_spec = importlib.util.spec_from_loader(
            signer_loader.name, signer_loader)
        signer = importlib.util.module_from_spec(signer_spec)
        signer_loader.exec_module(signer)
        publisher_pin = hashlib.sha256(public.read_bytes()).hexdigest()
        with self.assertRaises(signer.ReleaseSigningBlocked):
            signer.sign_release(
                archive=archive, manifest=manifest, commit=commit,
                private_key=private, trusted_public_key_sha256="0"*64,
                output_dir=self.root)
        self.assertFalse(statement.exists())
        signed = signer.sign_release(
            archive=archive, manifest=manifest, commit=commit,
            private_key=private,
            trusted_public_key_sha256=publisher_pin,
            output_dir=self.root)
        self.assertEqual(signed["status"],
                         "official_release_provenance_signed")
        self.assertEqual(signed["publisher_public_key_sha256"], publisher_pin)
        self.assertFalse(signed["live_no_drain_authorized"])
        self.assertFalse(signed["private_key_exported"])
        with self.assertRaises(signer.ReleaseSigningBlocked):
            signer.sign_release(
                archive=archive, manifest=manifest, commit=commit,
                private_key=private,
                trusted_public_key_sha256=publisher_pin,
                output_dir=self.root)
        self.assertTrue(statement.exists())
        self.assertTrue(signature.exists())

        def verify(**kwargs):
            return verifier.verify_signed_release(
                archive, manifest, statement, signature,
                expected_commit=kwargs.pop("expected_commit", commit),
                trusted_public_key=public,
                disposable_fixture=kwargs.pop("disposable_fixture", True),
                **kwargs,
            )

        proven = verify()
        self.assertTrue(proven["artifact_signature_verified"])
        self.assertEqual(proven["scope"], "disposable_fixture_only")
        self.assertFalse(proven["live_no_drain_authorized"])
        self.assertFalse(proven["remote_agent_quiescence_acked"])
        self.assertFalse(proven["external_jobs_acked"])

        # A caller cannot turn a fixture key into the root-owned trust anchor.
        with self.assertRaises(verifier.ReleaseProvenanceBlocked):
            verify(disposable_fixture=False)
        with self.assertRaises(verifier.ReleaseProvenanceBlocked):
            verify(expected_commit="b" * 40)

        # Integrity without the reviewable signature is insufficient.
        original_signature = signature.read_bytes()
        signature.write_bytes(b"x" * len(original_signature))
        with self.assertRaises(verifier.ReleaseProvenanceBlocked):
            verify()
        signature.write_bytes(original_signature)

        original_archive = archive.read_bytes()
        archive.write_bytes(original_archive + b"tampered")
        with self.assertRaises(verifier.ReleaseProvenanceBlocked):
            verify()
        archive.write_bytes(original_archive)
        self.assertTrue(verify()["artifact_signature_verified"])



class InstalledDaemonDriftGuardTest(unittest.TestCase):
    """Read-only identity comparison cannot authorize a live update."""

    @staticmethod
    def _module():
        path = ROOT / "update-manager/game-uptime-live-daemon-identity.py"
        loader = SourceFileLoader("dsm928_daemon_drift_guard_test", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def test_stable_identity_is_diagnostic_not_ack(self):
        module = self._module()
        snapshot = {
            "controller": {"identity_verified": True, "pid": 200,
                           "start_ticks": 500, "flock_opted_in_verified": True},
            "worker_group": {
                "all_nine_workers_verified": True,
                "observed_worker_count": 9,
                "supervisor_identity": {"pid": 300, "start_ticks": 600},
                "worker_identities": {
                    name: {"pid": 301 + i, "start_ticks": 601 + i}
                    for i, name in enumerate((
                        "scheduler_worker", "automation_worker",
                        "content_update_worker", "maintenance_worker",
                        "observability_retention_worker",
                        "content_upload_retention_worker",
                        "database_intelligence_worker", "hybrid_agent_worker",
                        "hybrid_customer_workspace_worker",
                    ))
                },
            },
            "live_no_drain_authorized": False,
        }
        result = module.compare_installed_daemon_observations(
            snapshot, dict(snapshot))
        self.assertEqual(result["status"], "stable_read_only_identity_only")
        self.assertTrue(result["identity_snapshots_stable"])
        for name in ("controller_mutations_acked", "worker_cycles_acked",
                     "remote_agents_acked", "external_jobs_acked",
                     "live_no_drain_authorized"):
            self.assertIs(result[name], False)

    def test_pid_drift_and_missing_worker_inventory_block(self):
        module = self._module()
        before = {
            "controller": {"identity_verified": True, "pid": 200},
            "worker_group": {"all_nine_workers_verified": True},
            "live_no_drain_authorized": False,
        }
        after = {
            "controller": {"identity_verified": True, "pid": 201},
            "worker_group": {"all_nine_workers_verified": False},
            "live_no_drain_authorized": False,
        }
        result = module.compare_installed_daemon_observations(before, after)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("controller_identity_changed", result["blockers"])
        self.assertIn("worker_group_identity_unverified", result["blockers"])
        self.assertFalse(result["live_no_drain_authorized"])


if __name__ == "__main__":
    unittest.main()
