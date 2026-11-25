"""Opt-in live-systemd, disposable-unit rehearsal for #928 (never runs DSM update).

Runs only with CAPIVARA_DSM928_SYSTEMD_E2E=1 and root; creates two uniquely
named NON-Capivara transient sleep units, so the game Agent cannot discover or
reconcile them. Exercises an isolated file transaction plus rollback with the
real systemd MainPID/start stamp invariant on both processes.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from uuid import uuid4
from importlib.machinery import SourceFileLoader

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("dsm928_uptime_plan", str(ROOT/"update-manager/game-uptime-plan.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
plan = importlib.util.module_from_spec(spec)
loader.exec_module(plan)

tx_loader = SourceFileLoader(
    "dsm928_disposable_transaction",
    str(ROOT/"update-manager/game-uptime-transaction.py"),
)
tx_spec = importlib.util.spec_from_loader(tx_loader.name, tx_loader)
transaction = importlib.util.module_from_spec(tx_spec)
tx_loader.exec_module(transaction)

guard_loader = SourceFileLoader(
    "dsm928_disposable_reverse_dependency_guard",
    str(ROOT / "update-manager/game-uptime-guard.py"),
)
guard_spec = importlib.util.spec_from_loader(guard_loader.name, guard_loader)
guard = importlib.util.module_from_spec(guard_spec)
guard_loader.exec_module(guard)

from update_game_uptime_real_update_functions_test import (
    create_tiny_release_fixture, run_real_update_fns,
)
from update_game_uptime_main_path_test import main_rehearsal


def disposable_systemd_host(installed_storage=Path("/opt/dsm/runtime/hybrid-instance-storage"),
                            unit_output=None):
    """Deny systemd exercises on installed DSM hosts or any with live games."""
    if installed_storage.exists() or not Path("/run/systemd/system").is_dir():
        return False
    if unit_output is None:
        try:
            result = subprocess.run(
                ("systemctl", "list-units", "--type=service", "--state=active",
                 "--all", "--no-legend", "--plain", "capivara-instance-*.service"),
                text=True, capture_output=True, timeout=8, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode != 0:
            return False
        unit_output = result.stdout
    return not bool(unit_output.strip())


class DisposableSystemdHostSafetyTests(unittest.TestCase):
    def test_refuses_installed_dsm_even_when_opted_in(self):
        with tempfile.TemporaryDirectory(prefix="dsm928-test-installed-") as tmp:
            installed=Path(tmp)/"hybrid-instance-storage"
            installed.mkdir()
            self.assertFalse(disposable_systemd_host(installed, unit_output=""))

    def test_refuses_active_game_service(self):
        with tempfile.TemporaryDirectory(prefix="dsm928-test-units-") as tmp:
            self.assertFalse(disposable_systemd_host(
                Path(tmp)/"absent", unit_output="capivara-instance-minecraft-005.service loaded active running"
            ))


class DisposableSystemdNoDrainTest(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CAPIVARA_DSM928_SYSTEMD_E2E") != "1":
            self.skipTest("opt-in required: CAPIVARA_DSM928_SYSTEMD_E2E=1")
        if os.geteuid() != 0 or not shutil.which("systemd-run"):
            self.skipTest("requires root and systemd-run")
        if not disposable_systemd_host():
            self.skipTest("refuse transient systemd test on a DSM or live-game host")
        self.units = []
        self.addCleanup(self._stop_units)
        self.temp = tempfile.TemporaryDirectory(prefix="dsm928-e2e-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.prefix = "dsm928-e2e-" + uuid4().hex[:10]

    @staticmethod
    def _run(*args):
        return subprocess.run(args, text=True, capture_output=True, timeout=15, check=True)

    def _start(self, suffix):
        unit = f"{self.prefix}-{suffix}.service"
        self._run("systemd-run", "--unit", unit[:-8], "--collect",
                  "--property=Type=simple", "/usr/bin/sleep", "180")
        self.units.append(unit)
        for _ in range(30):
            state = self._snapshot(unit)
            if state["state"] == "active" and state["pid"] > 1 and state["started"] > 0:
                return state
            time.sleep(0.1)
        self.fail(f"disposable unit did not start: {unit}")

    def _snapshot(self, unit):
        p = self._run("systemctl", "show", unit, "-p", "MainPID",
                      "-p", "ExecMainStartTimestampMonotonic", "-p", "ActiveState")
        values = dict(line.split("=",1) for line in p.stdout.splitlines() if "=" in line)
        return {"unit":unit, "pid":int(values.get("MainPID","0")),
                "started":int(values.get("ExecMainStartTimestampMonotonic","0")),
                "state":values.get("ActiveState")}

    def _stop_units(self):
        for unit in reversed(getattr(self, "units", [])):
            subprocess.run(("systemctl","stop",unit), capture_output=True,
                           text=True, timeout=15, check=False)

    def _assert_unchanged(self, originals):
        for prior in originals:
            self.assertEqual(self._snapshot(prior["unit"]), prior)

    def test_systemd_exposes_every_reverse_dependency_for_fail_closed_preflight(self):
        """Use a disposable transient unit to validate the host's systemd ABI.

        Without this proof, extra reverse links in the read-only guard could
        incorrectly mark otherwise safe game units as 'incomplete evidence'.
        """
        unit = self._start("reverse-dependencies")
        properties = guard.DEPENDENCY_PROPERTIES
        self.assertEqual(len(set(properties)), len(properties))
        observed = self._run("systemctl", "show", unit["unit"],
                             *(f"--property={name}" for name in properties),
                             "--no-pager")
        returned = {line.split("=", 1)[0] for line in observed.stdout.splitlines()
                    if "=" in line}
        self.assertEqual(set(properties), returned)
        self.assertEqual(self._snapshot(unit["unit"]), unit)

    def test_real_release_package_cannot_bypass_no_drain_gate_with_live_disposable_pids(self):
        """#928 stage 2.2: actual DSM release bytes must fail closed.

        Two genuinely active transient systemd game stand-ins survive an
        attempted no-drain update with the real release TAR. The fixture
        signer proves only disposable origin, never operational compatibility.
        This test does not execute a live updater or authorize --no-drain.
        """
        import tarfile
        from update_game_uptime_main_path_test import fixture_signer

        originals = [self._start("real-release-dayz"),
                     self._start("real-release-minecraft")]
        fixture = self.workspace / "real-package-no-drain"
        fixture.mkdir(mode=0o700)
        create_tiny_release_fixture(fixture)
        (fixture / "installed/version").write_text("2.0.0")
        output = self.workspace / "release-artifact"
        output.mkdir()
        build = subprocess.run(
            ("bash", str(ROOT / "release/build_release.sh"), "HEAD", str(output)),
            text=True, capture_output=True, check=False, timeout=150,
        )
        self.assertEqual(build.returncode, 0,
                         build.stderr[-1600:] + build.stdout[-600:])
        version = (ROOT / "version").read_text(encoding="utf-8").strip()
        name = "capivara-dsm-" + version
        archive = output / (name + ".tar.gz")
        self.assertTrue(archive.is_file(), str(archive))
        expanded = self.workspace / "expanded-release"
        expanded.mkdir()
        with tarfile.open(archive, "r:gz") as package:
            package.extractall(expanded, filter="data")
        shutil.rmtree(fixture / "new-payload")
        (expanded / name).rename(fixture / "new-payload")
        # Fixture-only signature must not turn a real, incompatible release
        # into a no-drain candidate. The policy must reject before backup,
        # even while the two real systemd processes are active.
        fixture_signer().seal_test_fixture(fixture)
        self._assert_unchanged(originals)
        result = main_rehearsal(fixture, "no_drain_success")
        self.assertEqual(result.returncode, 2,
                         result.stdout[-800:] + result.stderr[-1200:])
        self.assertIn("DISPOSABLE_REHEARSAL_BLOCKED", result.stderr)
        self.assertTrue(
            "compatibility gate blocked" in result.stderr
            or "release tier blocked" in result.stderr,
            result.stderr[-1400:],
        )
        self.assertEqual((fixture / "installed/version").read_text(), "2.0.0")
        self.assertFalse((fixture / "dsm928-composite-journal").exists())
        self.assertEqual(list((fixture / "backups").glob("*.tar.gz")), [])
        self.assertFalse((fixture / "steps").exists())
        self._assert_unchanged(originals)

        # #928 stage 2.3: the same verified release archive is also the
        # BASELINE of a compatible *synthetic* candidate. Only presentation
        # and fixture-version bytes differ, never Agent/systemd/supervisor.
        # This derivative is not an authentic, releasable DSM package and
        # cannot be used to authorize --no-drain on installed hosts.
        import hashlib
        checksum = output / (archive.name + ".sha256")
        expected_hash, filename = checksum.read_text().strip().split()
        self.assertEqual(filename, archive.name)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                         expected_hash)
        # Stage 2.5: check the real TAR with independently supplied commit,
        # version and digest pins before using it as test baseline. This
        # remains INTEGRITY ONLY, not a publisher signature/no-drain approval.
        from importlib.machinery import SourceFileLoader
        from importlib.util import module_from_spec, spec_from_loader
        verifier_path=ROOT / "update-manager/game-uptime-release-integrity.py"
        verifier_spec=spec_from_loader(
            "dsm928_pinned_release_integrity",
            SourceFileLoader("dsm928_pinned_release_integrity",str(verifier_path)),
        )
        verifier=module_from_spec(verifier_spec)
        verifier_spec.loader.exec_module(verifier)
        commit=subprocess.check_output(
            ("git","rev-parse","HEAD"),cwd=ROOT,text=True,
        ).strip()
        verified=verifier.verify_pinned_archive(
            archive,expected_sha256=expected_hash,
            expected_git_commit=commit,expected_version=version,
        )
        self.assertTrue(verified["checksum_matches_trusted_pin"])
        self.assertTrue(verified["manifest_bound_to_commit"])
        self.assertFalse(verified["release_origin_authenticated"])
        self.assertFalse(verified["remote_agent_quiescence_acked"])
        self.assertFalse(verified["live_no_drain_authorized"])
        for changes in (
            {"expected_sha256":"0"*64},
            {"expected_git_commit":"0"*40},
            {"expected_version":"0.0.0-test"},
        ):
            with self.subTest(stage="2.5",rejected_pin=tuple(changes)):
                pins={"expected_sha256":expected_hash,
                      "expected_git_commit":commit,
                      "expected_version":version}
                pins.update(changes)
                with self.assertRaises(verifier.ReleaseIntegrityError):
                    verifier.verify_pinned_archive(archive,**pins)
        # #928 stage 2.6: signed publisher pin and authenticated actor
        # quorum in ONE disposable security fence, using this same TAR and
        # the same two already-live systemd game stand-ins.
        import hmac
        import secrets
        import time
        gate_path = ROOT / "update-manager/game-uptime-security-fence.py"
        gate_loader = SourceFileLoader("dsm928_disposable_security_fence", str(gate_path))
        gate_spec = spec_from_loader(gate_loader.name, gate_loader)
        gate = module_from_spec(gate_spec)
        gate_spec.loader.exec_module(gate)
        security = self.workspace / "stage-2-6-security"
        security.mkdir(mode=0o700)
        (security / "fixture-owner").write_bytes(b"DSM928_DISPOSABLE_FIXTURE_V1\n")
        private = security / "signer-private.pem"
        public = security / "signer-public.pem"
        self._run("openssl", "genpkey", "-algorithm", "ED25519",
                  "-out", str(private))
        self._run("openssl", "pkey", "-in", str(private),
                  "-pubout", "-out", str(public))
        transaction_id = secrets.token_hex(16)
        approval = {
            "kind": "DSM928DisposableSignedApproval",
            "schema_version": 1,
            "scope": "disposable_only_not_production",
            "transaction_id": transaction_id,
            "release_sha256": expected_hash,
            "release_commit": commit,
            "release_version": version,
            "roles": ["agent", "controller", "external_jobs", "worker"],
            "issued_at": int(time.time()),
            "expires_at": int(time.time()) + 300,
        }
        approval_path = security / "approved-fixture.json"
        approval_path.write_bytes(gate.canonical(approval))
        signature = security / "approved-fixture.sig"
        self._run("openssl", "pkeyutl", "-sign",
                  "-inkey", str(private), "-rawin",
                  "-in", str(approval_path), "-out", str(signature))
        actor_keys = {role: os.urandom(32) for role in approval["roles"]}
        acknowledgements = []
        for role in approval["roles"]:
            ack = {
                "kind": "DSM928DisposableQuiescenceAck",
                "role": role, "transaction_id": transaction_id,
                "release_sha256": expected_hash,
                "status": "quiescent", "pending_jobs": 0,
            }
            ack["hmac_sha256"] = hmac.new(
                actor_keys[role], gate.canonical(ack),
                hashlib.sha256).hexdigest()
            acknowledgements.append(ack)
        kwargs = {
            "archive": archive,
            "release_sha256": expected_hash,
            "release_commit": commit,
            "release_version": version,
            "transaction_id": transaction_id,
            "approval_file": approval_path,
            "signature_file": signature,
            "publisher_public_key": public,
            "trusted_publisher_key_sha256":
                hashlib.sha256(public.read_bytes()).hexdigest(),
            "acknowledgements": acknowledgements,
            "actor_keys": actor_keys,
        }
        with self.assertRaises(gate.SecurityFenceError):
            gate.verify_disposable_fence(
                security, **{**kwargs, "trusted_publisher_key_sha256": "0"*64})
        with self.assertRaises(gate.SecurityFenceError):
            gate.verify_disposable_fence(
                security, **{**kwargs, "acknowledgements": acknowledgements[:-1]})
        tampered = [dict(x) for x in acknowledgements]
        tampered[1]["pending_jobs"] = 1
        with self.assertRaises(gate.SecurityFenceError):
            gate.verify_disposable_fence(
                security, **{**kwargs, "acknowledgements": tampered})
        stale = [dict(x) for x in acknowledgements]
        stale[0]["transaction_id"] = "f"*32
        with self.assertRaises(gate.SecurityFenceError):
            gate.verify_disposable_fence(
                security, **{**kwargs, "acknowledgements": stale})
        self.assertFalse((security / "dsm928-security-fence.json").exists())
        self._assert_unchanged(originals)
        receipt = gate.verify_disposable_fence(security, **kwargs)
        self.assertEqual(receipt["status"], "verified_fixture_only")
        self.assertTrue(receipt["publisher_signature_verified_under_test_pin"])
        self.assertTrue(receipt["fixture_actor_quorum_verified"])
        self.assertFalse(receipt["trusted_production_publisher_configured"])
        self.assertFalse(receipt["operational_remote_acks_verified"])
        self.assertFalse(receipt["live_no_drain_authorized"])
        self.assertEqual(
            json.loads((security / "dsm928-security-fence.json").read_text()),
            receipt)
        with self.assertRaises(gate.SecurityFenceError):
            gate.verify_disposable_fence(security, **kwargs)
        self._assert_unchanged(originals)

        # Unified final rehearsal: use the REAL release TAR and independent
        # RSA signed provenance from the existing release-verification contract.
        # These are ephemeral CI keys, never a production signing authority.
        bridge_loader = SourceFileLoader(
            "dsm928_consolidated_disposable_transaction",
            str(ROOT / "update-manager/game-uptime-consolidated-transaction.py"))
        bridge_spec = spec_from_loader(bridge_loader.name, bridge_loader)
        bridge = module_from_spec(bridge_spec)
        bridge_spec.loader.exec_module(bridge)
        release_manifest = output / (name + ".manifest.json")
        signed_statement = output / (name + ".provenance.json")
        signed_signature = output / (name + ".provenance.sig")
        publisher_private = security / "publisher-private-rsa.pem"
        publisher_public = security / "publisher-public-rsa.pem"
        self._run("openssl", "genpkey", "-algorithm", "RSA",
                  "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(publisher_private))
        self._run("openssl", "pkey", "-in", str(publisher_private),
                  "-pubout", "-out", str(publisher_public))
        statement_body = {
            "kind": "CapivaraDSMReleaseProvenance",
            "schema_version": 1,
            "repository": "EzequielRibeiro/Distributed-Server-Manager",
            "git_commit": commit,
            "version": version,
            "archive": archive.name,
            "archive_sha256": expected_hash,
            "manifest_sha256": hashlib.sha256(release_manifest.read_bytes()).hexdigest(),
        }
        signed_statement.write_text(
            json.dumps(statement_body, sort_keys=True, separators=(",", ":")) + "\n")
        self._run("openssl", "dgst", "-sha256", "-sign",
                  str(publisher_private), "-out", str(signed_signature),
                  str(signed_statement))
        publisher_pin = hashlib.sha256(publisher_public.read_bytes()).hexdigest()

        def current_units():
            listing = self._run(
                "systemctl", "list-units", "--type=service", "--state=active",
                "--no-legend", "--plain", f"{self.prefix}-*.service")
            return [line.split()[0] for line in listing.stdout.splitlines()
                    if line.strip()]

        def inspect_game(name):
            state = self._snapshot(name)
            unit_config = self._run("systemctl", "cat", name).stdout
            state["unit_config_sha256"] = hashlib.sha256(
                unit_config.encode()).hexdigest()
            return state

        # #928: real Controller/Worker flock ownership is retained for the
        # entire disposable update/rollback, rather than merely sampled.
        import fcntl
        scope_loader = SourceFileLoader(
            "dsm928_local_scope_lease",
            str(ROOT / "update-manager/game-uptime-local-scope-lease.py"))
        scope_spec = spec_from_loader(scope_loader.name, scope_loader)
        local_scope = module_from_spec(scope_spec)
        scope_spec.loader.exec_module(local_scope)

        # Stage 2.2 moved the extracted tree into the incompatible fixture.
        # Reuse that verified package instead of its now-empty old path.
        real_tree = fixture / "new-payload"
        self.assertTrue((real_tree / "agents/linux/runtime/console_supervisor.py").is_file())
        for mode, expected_version, expected_status in (
            ("no_drain_success", "2.0.999-fixture", "verified"),
            ("no_drain_fail_after_apply", "2.0.998-fixture", "rolled_back"),
        ):
            with self.subTest(stage="2.3", mode=mode):
                workspace = self.workspace / ("real-package-compatible-" + mode)
                workspace.mkdir(mode=0o700)
                create_tiny_release_fixture(workspace)
                installed = workspace / "installed"
                candidate = workspace / "new-payload"
                for root, fixture_version in (
                    (installed, "2.0.998-fixture"),
                    (candidate, "2.0.999-fixture"),
                ):
                    shutil.copytree(real_tree, root, dirs_exist_ok=True)
                    (root / "version").write_text(fixture_version)
                # A durable database file belongs to the protected fixture
                # state, not to release impact. Mirror its metadata in the
                # candidate as the existing compatible harness already does.
                target_db = candidate / "data/database.txt"
                target_db.parent.mkdir(parents=True, exist_ok=True)
                target_db.write_bytes(
                    (installed / "data/database.txt").read_bytes())
                web = Path("dashboard/web/presentation.js")
                original_web = (installed / web).read_bytes()
                (candidate / web).write_bytes(
                    original_web + b"\n// DSM928 fixture-only compatible presentation update\n"
                )
                impact = plan.analyze(installed, candidate)
                self.assertEqual(impact["change_tier"],
                                 "control_plane_restart_candidate")
                self.assertFalse(impact["live_no_drain_authorized"])
                fixture_signer().seal_test_fixture(workspace)
                self._assert_unchanged(originals)
                # One signed-origin → four-role ACK → durable transaction
                # chain for apply and rollback, using existing systemd units.
                fence_root = self.workspace / ("consolidated-fence-" + mode)
                fence_root.mkdir(mode=0o700)
                (fence_root / "fixture-owner").write_bytes(
                    b"DSM928_DISPOSABLE_FIXTURE_V1\n")
                nonce = secrets.token_hex(16)
                bounded_approval = {
                    **approval, "transaction_id": nonce,
                    "issued_at": int(time.time()),
                    "expires_at": int(time.time()) + 300,
                }
                bounded_approval_path = fence_root / "approval.json"
                bounded_approval_path.write_bytes(gate.canonical(bounded_approval))
                bounded_signature = fence_root / "approval.sig"
                self._run("openssl", "pkeyutl", "-sign", "-inkey",
                          str(private), "-rawin", "-in",
                          str(bounded_approval_path), "-out", str(bounded_signature))
                bounded_acks = []
                for role in bounded_approval["roles"]:
                    ack = {
                        "kind": "DSM928DisposableQuiescenceAck",
                        "role": role, "transaction_id": nonce,
                        "release_sha256": expected_hash,
                        "status": "quiescent", "pending_jobs": 0,
                    }
                    ack["hmac_sha256"] = hmac.new(
                        actor_keys[role], gate.canonical(ack),
                        hashlib.sha256).hexdigest()
                    bounded_acks.append(ack)
                integrated_kwargs = {
                    "archive": archive, "manifest": release_manifest,
                    "statement": signed_statement,
                    "release_signature": signed_signature,
                    "reviewed_commit": commit,
                    "publisher_public_key": publisher_public,
                    "expected_publisher_key_sha256": publisher_pin,
                    "security_workspace": fence_root,
                    "security_approval": bounded_approval_path,
                    "security_signature": bounded_signature,
                    "security_publisher_public_key": public,
                    "security_key_sha256":
                        hashlib.sha256(public.read_bytes()).hexdigest(),
                    "transaction_id": nonce,
                    "actor_acks": bounded_acks,
                    "actor_keys": actor_keys,
                    "units": [unit["unit"] for unit in originals],
                    "inspect": inspect_game,
                    "list_units": current_units,
                    "execute_fixture": lambda: main_rehearsal(workspace, mode),
                    "expected_journal_status": expected_status,
                }
                with self.assertRaises(bridge.ConsolidatedTransactionBlocked):
                    bridge.run_disposable_integrated(
                        workspace, **{**integrated_kwargs,
                                      "expected_publisher_key_sha256": "0"*64})
                self.assertFalse((workspace / "backups").exists())
                self.assertFalse((fence_root / "dsm928-security-fence.json").exists())
                # Preprovision only /tmp lock inodes, never /run or /opt/dsm.
                scope_root = self.workspace / ("local-scope-" + mode)
                scope_root.mkdir(mode=0o700)
                (scope_root / "fixture-owner").write_bytes(
                    b"DSM928_DISPOSABLE_FIXTURE_V1\n")
                runtime_parent = scope_root / "runtime"
                runtime_dir = runtime_parent / "run"
                state_dir = scope_root / "state"
                worker_dir = runtime_dir / "worker-operations"
                for folder in (runtime_parent, runtime_dir, state_dir, worker_dir):
                    folder.mkdir(mode=0o700)
                # The real preparer requires traversable hold directories;
                # the outer disposable workspace remains private.
                runtime_parent.chmod(0o755)
                runtime_dir.chmod(0o755)
                controller_lock = runtime_dir / "controller-agent-http.lock"
                scoped_locks = [controller_lock] + [
                    worker_dir / (worker + ".lock")
                    for worker in local_scope.WORKERS
                ]
                for lockfile in scoped_locks:
                    lockfile.touch(mode=0o600)
                    lockfile.chmod(0o600)
                hold_path = runtime_dir / "no-drain-maintenance.json"
                pending_path = state_dir / "no-drain-pending.json"
                hold_path.write_text(json.dumps({
                    "kind": "CapivaraDSMNoDrainMaintenanceHold",
                    "schema_version": 1,
                    "transaction_id": nonce,
                    "issued_at": int(time.time()),
                    "expires_at": int(time.time()) + 300,
                }))
                hold_path.chmod(0o600)
                lease_args = dict(
                    transaction_id=nonce, release_sha256=expected_hash,
                    expected_controller_uid=os.geteuid(),
                    expected_worker_uid=os.geteuid(),
                    controller_lock=controller_lock, worker_lock_dir=worker_dir,
                    hold_path=hold_path, pending_path=pending_path,
                    fixture_root=scope_root,
                )
                with self.assertRaises(local_scope.LocalScopeLeaseBlocked):
                    with local_scope.retain_local_scopes(
                            **{**lease_args, "transaction_id": "f" * 32}):
                        pass
                # A durable pending-recovery marker MUST block even if the
                # current hold is valid; do not auto-retry interrupted work.
                pending_path.write_text("interrupted")
                with self.assertRaisesRegex(
                        local_scope.LocalScopeLeaseBlocked,
                        "persistent_recovery_pending"):
                    with local_scope.retain_local_scopes(**lease_args):
                        pass
                pending_path.unlink()
                # A competing Worker must block the whole transaction, not
                # just one diagnostic snapshot.
                busy = os.open(scoped_locks[1], os.O_RDWR)
                try:
                    fcntl.flock(busy, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    with self.assertRaisesRegex(
                            local_scope.LocalScopeLeaseBlocked,
                            "operation_in_flight"):
                        with local_scope.retain_local_scopes(**lease_args):
                            pass
                finally:
                    fcntl.flock(busy, fcntl.LOCK_UN)
                    os.close(busy)
                # Replace the hand-built test marker with fresh durable
                # evidence from the real coordinator, under the same locks.
                hold_path.unlink()
                lease_args["prepare_fresh_fixture"] = True
                fixture_ids = ["fixture-agent-online", "fixture-agent-offline"]
                lease_args["expected_fixture_agent_ids"] = fixture_ids
                issued_at = int(time.time())
                lease_args["shared_lease_window"] = (issued_at, issued_at + 600)
                binding_path = state_dir / "no-drain-release-binding.json"
                inventory_path = state_dir / "no-drain-agent-inventory.json"
                helper_lock = runtime_dir / "agent-privileged-operations.lock"
                child_lock = runtime_dir / "agent-finalization-operations.lock"
                helper_lock.touch(mode=0o600)
                helper_lock.chmod(0o600)
                child_lock.touch(mode=0o660)
                child_lock.chmod(0o660)
                os.chown(child_lock, os.geteuid(), os.getegid())
                # Both existing helper lock families are mandatory before
                # the fresh transaction journal can be created.
                for operation_lock in (helper_lock, child_lock):
                    busy = os.open(operation_lock, os.O_RDWR)
                    try:
                        fcntl.flock(busy, fcntl.LOCK_SH | fcntl.LOCK_NB)
                        with self.assertRaisesRegex(
                                local_scope.LocalScopeLeaseBlocked,
                                "agent_operation_lock_unavailable"):
                            with local_scope.retain_local_scopes(**lease_args):
                                pass
                        self.assertFalse(pending_path.exists())
                        self.assertFalse(binding_path.exists())
                        self.assertFalse(inventory_path.exists())
                    finally:
                        os.close(busy)
                scoped_locks.extend((helper_lock, child_lock))
                def execute_only_under_locks():
                    pending = json.loads(pending_path.read_text())
                    binding = json.loads(binding_path.read_text())
                    self.assertEqual(pending["transaction_id"], nonce)
                    self.assertEqual((pending["issued_at"], pending["expires_at"]),
                                     lease_args["shared_lease_window"])
                    self.assertEqual(binding["release_sha256"], expected_hash)
                    inventory = json.loads(inventory_path.read_text())
                    self.assertEqual(inventory["agent_ids"], sorted(fixture_ids))
                    self.assertEqual(inventory["transaction_id"], nonce)
                    self.assertEqual(inventory["release_sha256"], expected_hash)
                    self.assertFalse(pending["live_no_drain_authorized"])
                    # This callback is now invoked INSIDE the coordinator's
                    # mandatory local scope lease, never by the test caller.
                    for lockfile in scoped_locks:
                        outsider = os.open(lockfile, os.O_RDWR)
                        try:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(outsider, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        finally:
                            os.close(outsider)
                    self._assert_unchanged(originals)
                    return main_rehearsal(workspace, mode)

                integrated_kwargs["execute_fixture"] = execute_only_under_locks
                integrated_kwargs["local_scope_kwargs"] = lease_args
                proof = bridge.run_disposable_integrated(
                    workspace, **integrated_kwargs)
                self.assertTrue(proof["fresh_durable_fixture_evidence"])
                self.assertTrue(proof["fixture_agent_inventory_retained"])
                self.assertTrue(proof["fixture_privileged_helper_lock_retained"])
                self.assertTrue(proof["fixture_finalization_child_lock_retained"])
                self.assertFalse(proof["external_jobs_acked"])
                self.assertTrue(proof["local_controller_lock_held_during_transaction"])
                # Evidence survives scope exit; a fresh transaction cannot
                # mistake an interrupted journal for a new preparation.
                self.assertTrue(pending_path.is_file())
                self.assertTrue(binding_path.is_file())
                self.assertTrue(inventory_path.is_file())
                self.assertEqual(json.loads(inventory_path.read_text())["agent_ids"],
                                 sorted(fixture_ids))
                with self.assertRaisesRegex(
                        local_scope.LocalScopeLeaseBlocked,
                        "persistent_recovery_pending"):
                    with local_scope.retain_local_scopes(**lease_args):
                        pass
                # Existing evidence remains blocked for apply, but a separate
                # inspection may retain the same locks without replay/cleanup.
                recovery_args = {**lease_args, "prepare_fresh_fixture": False,
                                 "expected_fixture_agent_ids": None,
                                 "inspect_existing_prepared": True,
                                 "expected_recovery_agent_ids": fixture_ids}
                saved = {p: p.read_bytes() for p in
                         (hold_path, pending_path, binding_path, inventory_path)}
                with local_scope.retain_local_scopes(**recovery_args) as recovery:
                    self.assertTrue(recovery["existing_prepared_recovery_inspection_only"])
                    self.assertFalse(recovery["fresh_durable_fixture_evidence"])
                    self.assertFalse(recovery["live_no_drain_authorized"])
                    recovery["checkpoint"]()
                    for lockfile in scoped_locks:
                        outsider = os.open(lockfile, os.O_RDONLY)
                        try:
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(outsider, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        finally:
                            os.close(outsider)
                self.assertEqual({p: p.read_bytes() for p in saved}, saved)
                with self.assertRaisesRegex(local_scope.LocalScopeLeaseBlocked,
                                            "local_scope_no_longer_retained"):
                    recovery["checkpoint"]()
                with self.assertRaises(local_scope.LocalScopeLeaseBlocked):
                    with local_scope.retain_local_scopes(
                            **{**recovery_args, "shared_lease_window":
                               (issued_at, issued_at + 601)}):
                        pass
                with self.assertRaises(local_scope.LocalScopeLeaseBlocked):
                    with local_scope.retain_local_scopes(
                            **{**recovery_args, "expected_recovery_agent_ids": fixture_ids[:1]}):
                        pass
                self.assertEqual(proof["local_worker_lock_count_held_during_transaction"], 9)
                self.assertFalse(proof["controller_routes_opted_in_verified"])
                self.assertFalse(proof["worker_process_inventory_verified"])
                self._assert_unchanged(originals)
                # After return, all descriptors must have been released.
                for lockfile in scoped_locks:
                    outsider = os.open(lockfile, os.O_RDWR)
                    try:
                        fcntl.flock(outsider, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(outsider, fcntl.LOCK_UN)
                    finally:
                        os.close(outsider)
                self.assertEqual(proof["journal_status"], expected_status)
                self.assertEqual(proof["units_preserved"], 2)
                self.assertTrue(proof["fixture_publisher_signed"])
                self.assertTrue(proof["fixture_actor_acks_verified"])
                self.assertFalse(proof["operational_agents_quiesced"])
                self.assertFalse(proof["live_no_drain_authorized"])
                with self.assertRaises(bridge.ConsolidatedTransactionBlocked):
                    bridge.run_disposable_integrated(
                        workspace, **integrated_kwargs)
                self.assertEqual((installed / "version").read_text().strip(),
                                 expected_version)
                self.assertEqual(
                    (installed / web).read_bytes(),
                    (candidate / web).read_bytes()
                    if mode == "no_drain_success" else original_web,
                )
                journal = json.loads((
                    workspace / "dsm928-composite-journal/game-uptime-transaction.json"
                ).read_text())
                self.assertEqual(journal["status"], expected_status)
                self.assertTrue(journal["strict_inventory"])
                self.assertFalse(journal["live_no_drain_authorized"])
                self.assertEqual(
                    (installed / "runtime/hybrid-instance-storage/minecraft005"
                     "/world/level.dat").read_bytes(), b"saved-world-private-test")
                self.assertEqual(
                    (installed / "runtime/artifact-transfers/job-001/upload.part"
                     ).read_bytes(), b"in-flight-upload-private-test")
                self.assertEqual(
                    (installed / "runtime/hybrid-agent-state/backup-index/keep.txt"
                     ).read_text(), "protected")
                self.assertEqual(
                    (installed / "data/database.txt").read_text(), "db durable")
                self.assertEqual(len(list(
                    (workspace / "backups").glob("*.tar.gz"))), 1)
                self.assertFalse((workspace / "steps").exists())
                self._assert_unchanged(originals)

    def test_two_systemd_processes_survive_actual_updater_main_and_failure_rollback(self):
        """Call actual update.sh main() with ONLY production-facing hooks stubbed."""
        originals = [self._start("main-alpha"), self._start("main-beta")]
        for mode, outcome_version in (("success", "2.0.999"), ("fail_after_apply", "2.0.998")):
            with self.subTest(mode=mode):
                fixture = self.workspace/("real-main-" + mode)
                create_tiny_release_fixture(fixture)
                (fixture/"installed/version").write_text("2.0.998")
                (fixture/"new-payload/version").write_text("2.0.999")
                result = main_rehearsal(fixture, mode)
                self.assertEqual(result.returncode == 0, mode == "success",
                                 (result.stdout[-500:], result.stderr[-500:]))
                self.assertEqual((fixture/"installed/version").read_text().strip(), outcome_version)
                self.assertEqual((fixture/"installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat").read_bytes(),
                                 b"saved-world-private-test")
                self.assertEqual((fixture/"installed/data/database.txt").read_text(),"db durable")
                self._assert_unchanged(originals)

    def test_auth_agent_main_rehearsal_and_two_systemd_pids_stay_consistent(self):
        """One isolated #928 cross-contract proof; never authorizes production.

        Exercise actual Linux Agent heartbeat over credentialed HTTP before
        and after a Controller dispatcher restart, the real update.sh main()
        disposable no-drain entry (success and failed apply/rollback), and
        two independent real systemd processes. The main() fixture uses a
        synthetic game inventory: this is NOT a full daemon/update E2E.
        """
        from update_game_uptime_agent_runtime_restart_test import (
            LinuxAgentProcessHeartbeatTests,
        )
        from update_game_uptime_main_path_test import MainPathRehearsalTest

        originals = [self._start("contract-minecraft"),
                     self._start("contract-dayz")]
        agent = LinuxAgentProcessHeartbeatTests(
            "test_real_agent_process_reconnects_to_restarted_controller")
        agent.setUp()
        self.addCleanup(agent.doCleanups)

        def heartbeat():
            result = agent.invoke()
            self.assertEqual(result.returncode, 0, result.stderr[-1400:])
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(payload["wire_compatible"])
            self.assertFalse(payload["live_no_drain_authorized"])
            self.assertEqual(payload["health_status"], "online")
            self.assertEqual(payload["agent_id"], agent.controller.agent_id)
            return payload

        first = heartbeat()
        self._assert_unchanged(originals)
        for mode, target_version, journal_status in (
            ("no_drain_success", "2.0.999-fixture", "verified"),
            ("no_drain_fail_after_apply", "2.0.998-fixture", "rolled_back"),
        ):
            with self.subTest(mode=mode):
                main = MainPathRehearsalTest(
                    "test_disposable_no_drain_actual_main_success_preserves_data_and_never_drains")
                main.setUp()
                self.addCleanup(main.doCleanups)
                main.prepare_no_drain_fixture()
                result = main_rehearsal(main.root, mode)
                self.assertEqual(
                    result.returncode, 0 if mode == "no_drain_success" else 2,
                    result.stdout[-1200:] + result.stderr[-1200:])
                self.assertEqual(
                    (main.installed / "version").read_text().strip(),
                    target_version)
                self.assertEqual(main.world.read_bytes(), b"saved-world-private-test")
                self.assertEqual(main.upload.read_bytes(),
                                 b"in-flight-upload-private-test")
                self.assertFalse((main.root / "steps").exists(),
                                 "real game/Controller stop hooks must not run")
                receipt = json.loads((
                    main.root / "dsm928-composite-journal/game-uptime-transaction.json"
                ).read_text())
                self.assertEqual(receipt["status"], journal_status)
                self.assertTrue(receipt["strict_inventory"])
                self.assertEqual(len(receipt["original_units"]), 2)
                self.assertFalse(receipt["live_no_drain_authorized"])
                self._assert_unchanged(originals)

                # The Controller dispatcher is recreated against the same
                # durable disposable SQLite database; the Agent reconnects
                # using its actual HTTP client and existing credential.
                agent.controller._restart_controller_dispatcher()
                resumed = heartbeat()
                self.assertEqual(resumed["agent_id"], first["agent_id"])
                self._assert_unchanged(originals)

    def test_real_dashboard_and_hybrid_worker_restart_around_disposable_update(self):
        """Run actual DSM entrypoints under disposable systemd, never on DSM hosts.

        This validates the actual server_part22.py Dashboard entrypoint,
        credentialed Linux Agent HTTP against its integrated route, and Worker
        process restart around the guarded update.sh main() fixture. The Worker
        remains non-hybrid, and Agent host inventory/mutations are blocked by
        the reused fixture. Not a live no-drain update or complete Agent daemon.
        """
        import socket
        import sys
        from urllib.request import urlopen
        from urllib.error import URLError
        from update_game_uptime_main_path_test import MainPathRehearsalTest
        import update_game_uptime_agent_runtime_restart_test as agent_fixture_module

        # Reuse real ephemeral SQLite pairing/credentials, but route the Agent
        # to the ACTUAL production Controller HTTP composition instead of the
        # fixture's simplified dispatcher listener.
        agent_fixture = agent_fixture_module.LinuxAgentProcessHeartbeatTests(
            "test_real_agent_process_reconnects_to_restarted_controller")
        agent_fixture.setUp()
        self.addCleanup(agent_fixture.doCleanups)
        agent_fixture.controller._stop_http()

        original_games = [self._start("dashboard-game-a"),
                          self._start("dashboard-game-b")]
        root = self.workspace / "isolated-control-plane"
        for directory in ("dashboard/state", "data", "logs",
                          "runtime/hybrid-agent-state", "config"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        self.assertFalse((root / "config/agent.conf").exists())
        self.assertFalse((root / "runtime/hybrid-agent-state/agent.json").exists())

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        ping = f"http://127.0.0.1:{port}/ping"
        # Switch to the actually installed package source for the 2.4
        # integrated rehearsal. Earlier 2.1–2.3 coverage uses checkout code.
        runtime_source_root = ROOT

        def start_control(role, generation):
            pythonpath = os.pathsep.join(str(p) for p in (
                runtime_source_root, runtime_source_root / "database",
                runtime_source_root / "dashboard", runtime_source_root / "core",
                runtime_source_root / "agents/linux/runtime",
            ))
            common = (
                f"--setenv=DSM_ROOT={root}",
                f"--setenv=DSM_DATABASE={agent_fixture.controller.db_path}",
                "--setenv=DSM_DATABASE_DRIVER=sqlite",
                "--setenv=PYTHONDONTWRITEBYTECODE=1",
                f"--setenv=PYTHONPATH={pythonpath}",
            )
            unit = f"{self.prefix}-{role}-{generation}.service"
            args = ["systemd-run", "--unit", unit[:-8], "--collect",
                    "--property=Type=simple",
                    "--property=NoNewPrivileges=yes",
                    "--property=ProtectSystem=strict",
                    f"--property=ReadWritePaths={self.workspace}",
                    f"--property=ReadWritePaths={agent_fixture.controller.db_path.parent}",
                    "--property=IPAddressDeny=any",
                    "--property=IPAddressAllow=localhost",
                    *common]
            if role == "dashboard":
                args.extend((
                    "--setenv=DASHBOARD_HOST=127.0.0.1",
                    f"--setenv=DASHBOARD_PORT={port}",
                    # Canonical systemd/dsm-dashboard.service ExecStart.
                    sys.executable, str(runtime_source_root / "dashboard/server_part22.py"),
                ))
            else:
                args.extend((
                    "--setenv=DSM_HYBRID_HEARTBEAT_SECONDS=10",
                    sys.executable,
                    str(runtime_source_root / "dashboard/workers/hybrid_agent_worker.py"),
                ))
            self._run(*args)
            self.units.append(unit)
            for _ in range(90):
                snap = self._snapshot(unit)
                if snap["state"] == "active" and snap["pid"] > 1:
                    if role != "dashboard":
                        return snap
                    try:
                        with urlopen(ping, timeout=0.5) as response:
                            content = json.loads(response.read())
                            if response.status == 200 and content.get("status") == "ok":
                                return snap
                    except (OSError, ValueError, URLError):
                        pass
                if snap["state"] == "failed":
                    break
                time.sleep(0.1)
            status = subprocess.run(
                ("systemctl", "status", unit, "--no-pager"),
                text=True, capture_output=True, check=False, timeout=8)
            self.fail(f"isolated {role} failed startup: {status.stdout[-1400:]}")

        def stop_control(unit):
            self._run("systemctl", "stop", unit)
            for _ in range(50):
                state = self._snapshot(unit)
                if state["state"] in ("inactive", "failed"):
                    return
                time.sleep(0.1)
            self.fail(f"isolated control-plane unit did not stop: {unit}")

        def check_current(control):
            self._assert_unchanged(original_games)
            for entry in control.values():
                self.assertEqual(self._snapshot(entry["unit"]), entry)
                cmdline = (Path("/proc") / str(entry["pid"]) / "cmdline").read_bytes()
                expected_path = (runtime_source_root / "dashboard/workers/hybrid_agent_worker.py"
                                 if "worker" in entry["unit"]
                                 else runtime_source_root / "dashboard/server_part22.py")
                self.assertIn(os.fsencode(str(expected_path)), cmdline)
            with urlopen(ping, timeout=2) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["status"], "ok")

        def check_authenticated_agent(*, rejected=False):
            # Separate Agent interpreter, real config/urllib heartbeat and
            # no host discovery or mutation (the existing fixture forbids it).
            agent_fixture.controller.url = (
                f"http://127.0.0.1:{port}/api/agent/heartbeat")
            # Keep this phase telemetry-only: new Controller enrollment can
            # return an operational Doctor command, which must never be
            # executed by an isolated update acceptance test.
            result = agent_fixture.invoke(
                invalid_secret=rejected, read_only=True,
                source_root=runtime_source_root if runtime_source_root != ROOT else None,
            )
            if rejected:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Controller rejected request (401)",
                              result.stderr[-1400:])
                self._assert_unchanged(original_games)
                return
            self.assertEqual(result.returncode, 0,
                             result.stderr[-1400:] + result.stdout[-600:])
            details = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(details["wire_compatible"])
            self.assertFalse(details["live_no_drain_authorized"])
            self.assertEqual(details["agent_id"], agent_fixture.controller.agent_id)
            self.assertEqual(details["health_status"], "online")
            self.assertEqual(details["agent_source_path"],
                             str((runtime_source_root / "agents/linux/runtime/agent.py").resolve()))
            self._assert_unchanged(original_games)

        current = {
            "dashboard": start_control("dashboard", "before"),
            "worker": start_control("worker", "before"),
        }
        check_current(current)
        check_authenticated_agent()
        check_authenticated_agent(rejected=True)

        for generation, mode, expected, journal in (
            ("after-success", "no_drain_success", "2.0.999-fixture", "verified"),
            ("after-rollback", "no_drain_fail_after_apply",
             "2.0.998-fixture", "rolled_back"),
        ):
            with self.subTest(mode=mode):
                main = MainPathRehearsalTest(
                    "test_disposable_no_drain_actual_main_success_preserves_data_and_never_drains")
                main.setUp()
                self.addCleanup(main.doCleanups)
                main.prepare_no_drain_fixture()
                result = main_rehearsal(main.root, mode)
                self.assertEqual(result.returncode, 0 if mode == "no_drain_success" else 2,
                                 result.stdout[-900:] + result.stderr[-900:])
                self.assertEqual((main.installed / "version").read_text().strip(), expected)
                self.assertEqual(main.world.read_bytes(), b"saved-world-private-test")
                self.assertEqual(main.upload.read_bytes(),
                                 b"in-flight-upload-private-test")
                self.assertFalse((main.root / "steps").exists())
                receipt = json.loads((
                    main.root / "dsm928-composite-journal/game-uptime-transaction.json"
                ).read_text())
                self.assertEqual(receipt["status"], journal)
                self.assertFalse(receipt["live_no_drain_authorized"])
                check_current(current)

                # A deliberately orchestrated test-only control-plane restart;
                # production update.sh is NOT wired to these actual services.
                for service in ("worker", "dashboard"):
                    stop_control(current[service]["unit"])
                self._assert_unchanged(original_games)
                current = {
                    "dashboard": start_control("dashboard", generation),
                    "worker": start_control("worker", generation),
                }
                check_current(current)
                check_authenticated_agent()
                self.assertFalse((root / "config/agent.conf").exists())

        self.assertFalse((root / "runtime/hybrid-agent-state/agent.json").exists())
        self.assertFalse(Path("/opt/dsm/runtime/hybrid-instance-storage").exists())

        # #928 stage 2.4: run the genuine packaged Controller/Worker/Agent
        # source through the existing systemd+HTTP rehearsal, instead of
        # executing checkout code detached from the update under test.
        # Only protected fixture state and disposable units can be mutated.
        import hashlib
        import tarfile
        from update_game_uptime_main_path_test import fixture_signer
        from update_game_uptime_real_update_functions_test import create_tiny_release_fixture

        output = self.workspace / "integrated-release-artifact"
        output.mkdir()
        build = subprocess.run(
            ("bash", str(ROOT / "release/build_release.sh"), "HEAD", str(output)),
            text=True, capture_output=True, timeout=150, check=False,
        )
        self.assertEqual(build.returncode, 0,
                         build.stderr[-1500:] + build.stdout[-800:])
        version = (ROOT / "version").read_text().strip()
        name = "capivara-dsm-" + version
        archive = output / (name + ".tar.gz")
        sha_path = output / (archive.name + ".sha256")
        digest, filename = sha_path.read_text().strip().split()
        self.assertEqual(filename, archive.name)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), digest)
        unpack = self.workspace / "integrated-release-unpacked"
        unpack.mkdir()
        with tarfile.open(archive, "r:gz") as package:
            package.extractall(unpack, filter="data")
        release_source = unpack / name
        for required in ("dashboard/server_part22.py",
                         "dashboard/workers/hybrid_agent_worker.py",
                         "agents/linux/runtime/agent.py",
                         "agents/linux/runtime/game_uptime_agent_wire.py",
                         "agents/linux/runtime/console_supervisor.py"):
            self.assertTrue((release_source / required).is_file(), required)

        for mode, expected_version, expected_status in (
            ("no_drain_success", "2.0.999-fixture", "verified"),
            ("no_drain_fail_after_apply", "2.0.998-fixture", "rolled_back"),
        ):
            with self.subTest(stage="2.4", mode=mode):
                fixture = self.workspace / ("integrated-packaged-" + mode)
                fixture.mkdir(mode=0o700)
                create_tiny_release_fixture(fixture)
                installed = fixture / "installed"
                candidate = fixture / "new-payload"
                for tree, fixture_version in (
                    (installed, "2.0.998-fixture"),
                    (candidate, "2.0.999-fixture"),
                ):
                    shutil.copytree(release_source, tree, dirs_exist_ok=True)
                    (tree / "version").write_text(fixture_version)
                candidate_db = candidate / "data/database.txt"
                candidate_db.parent.mkdir(parents=True, exist_ok=True)
                candidate_db.write_bytes((installed / "data/database.txt").read_bytes())
                presentation = Path("dashboard/web/presentation.js")
                original_presentation = (installed / presentation).read_bytes()
                (candidate / presentation).write_bytes(
                    original_presentation + b"\n// disposable stage 2.4 presentation delta\n"
                )
                impact = plan.analyze(installed, candidate)
                self.assertEqual(impact["change_tier"],
                                 "control_plane_restart_candidate")
                self.assertFalse(impact["live_no_drain_authorized"])
                fixture_signer().seal_test_fixture(fixture)

                # Start the actual packaged entrypoints against the existing
                # isolated controller DB. Neither Agent inventory nor any
                # production command is enabled.
                for service in ("worker", "dashboard"):
                    stop_control(current[service]["unit"])
                self._assert_unchanged(original_games)
                runtime_source_root = installed
                generation = ("package-" + mode)
                current = {
                    "dashboard": start_control("dashboard", generation + "-before"),
                    "worker": start_control("worker", generation + "-before"),
                }
                check_current(current)
                check_authenticated_agent()
                check_authenticated_agent(rejected=True)

                # Exercise actual update.sh main() fixture file swap while
                # Controller/Worker execute code from that installation root.
                result = main_rehearsal(fixture, mode)
                self.assertEqual(
                    result.returncode,
                    0 if mode == "no_drain_success" else 2,
                    result.stderr[-1600:] + result.stdout[-900:],
                )
                self.assertEqual((installed / "version").read_text().strip(),
                                 expected_version)
                self.assertEqual((installed / presentation).read_bytes(),
                                 (candidate / presentation).read_bytes()
                                 if mode == "no_drain_success"
                                 else original_presentation)
                self.assertEqual(
                    (installed / "runtime/hybrid-instance-storage/minecraft005"
                     "/world/level.dat").read_bytes(), b"saved-world-private-test")
                self.assertEqual(
                    (installed / "runtime/artifact-transfers/job-001/upload.part"
                     ).read_bytes(), b"in-flight-upload-private-test")
                self.assertEqual(
                    (installed / "data/database.txt").read_text(), "db durable")
                self.assertFalse((fixture / "steps").exists())
                receipt = json.loads(
                    (fixture / "dsm928-composite-journal/game-uptime-transaction.json")
                    .read_text())
                self.assertEqual(receipt["status"], expected_status)
                self.assertTrue(receipt["strict_inventory"])
                self.assertFalse(receipt["live_no_drain_authorized"])
                check_current(current)
                self._assert_unchanged(original_games)

                # Stop/restart only the isolated control plane; the new
                # generation loads its code from the updated/rolled-back
                # installed tree and Agent talks to the restarted HTTP route.
                for service in ("worker", "dashboard"):
                    stop_control(current[service]["unit"])
                self._assert_unchanged(original_games)
                current = {
                    "dashboard": start_control("dashboard", generation + "-after"),
                    "worker": start_control("worker", generation + "-after"),
                }
                check_current(current)
                check_authenticated_agent()
                self._assert_unchanged(original_games)

        self.assertFalse(Path("/opt/dsm").exists())

    def test_real_worker_supervisor_group_restarts_without_draining_game_units(self):
        """Exercise unchanged worker.sh, nine harmless children, and real systemd.

        Production worker children are NEVER started. Every child executable
        is a self-contained sleep fixture inside a private, owner-marked /tmp
        root. The worker.sh bytes and lifecycle are real; operational worker
        code, database access and host reconciliation are out of scope.
        """
        import signal
        from update_game_uptime_main_path_test import MainPathRehearsalTest

        originals = [self._start("supervised-game-a"),
                     self._start("supervised-game-b")]
        fake_root = self.workspace / "supervisor-only-clone"
        workers = fake_root / "dashboard" / "workers"
        workers.mkdir(parents=True, mode=0o700)
        (fake_root / "logs").mkdir(mode=0o700)

        source = ROOT / "dashboard" / "workers" / "worker.sh"
        supervisor_script = workers / "worker.sh"
        supervisor_script.write_bytes(source.read_bytes())
        supervisor_script.chmod(0o700)
        self.assertEqual(source.read_bytes(), supervisor_script.read_bytes())
        expected_workers = (
            "scheduler_worker.sh",
            "automation_worker.py",
            "content_update_worker.py",
            "maintenance_worker.py",
            "observability_retention_worker.py",
            "content_upload_retention_worker.py",
            "database_intelligence_worker.py",
            "hybrid_agent_worker.py",
            "hybrid_customer_workspace_worker.py",
        )
        (workers / "scheduler_worker.sh").write_text(
            "#!/usr/bin/env bash\nexec /usr/bin/sleep 180\n", encoding="utf-8")
        (workers / "scheduler_worker.sh").chmod(0o700)
        for name in expected_workers[1:]:
            stub = workers / name
            stub.write_text(
                "import os, time\n"
                "from pathlib import Path\n"
                "if Path(__file__).name == 'hybrid_agent_worker.py':\n"
                "    assert os.environ.get('CAPIVARA_AGENT_MODE') == 'hybrid'\n"
                "    assert os.environ.get('CAPIVARA_DSM_ROOT') == "
                + repr(str(fake_root)) + "\n"
                "    assert os.environ.get('CAPIVARA_STEAM_HOME') == "
                + repr(str(fake_root)) + "\n"
                "time.sleep(180)\n", encoding="utf-8")

        unit = f"{self.prefix}-supervisor-clone.service"
        self._run(
            "systemd-run", "--unit", unit[:-8], "--collect",
            "--property=Type=simple", "--property=Restart=on-failure",
            "--property=RestartSec=1s",
            "--property=KillMode=control-group",
            "--property=NoNewPrivileges=yes",
            "--property=ProtectSystem=strict",
            f"--property=ReadWritePaths={fake_root}",
            "--property=IPAddressDeny=any",
            "--setenv=PYTHONDONTWRITEBYTECODE=1",
            f"--setenv=DSM_ROOT={fake_root}",
            "/usr/bin/bash", str(supervisor_script),
        )
        self.units.append(unit)
        log = fake_root / "logs" / "dashboard_worker.log"

        def running_snapshot(exclude_pid=0):
            for _ in range(100):
                snap = self._snapshot(unit)
                if (snap["state"] == "active"
                    and snap["pid"] > 1
                    and snap["started"] > 0
                    and snap["pid"] != exclude_pid):
                    children_file = (Path("/proc") / str(snap["pid"]) /
                                     "task" / str(snap["pid"]) / "children")
                    try:
                        children = [int(x) for x in
                                    children_file.read_text().strip().split()]
                    except OSError:
                        children = []
                    if len(children) == len(expected_workers):
                        return snap, children
                time.sleep(0.1)
            self.fail("real worker.sh never supervised all nine disposable children")

        before, children = running_snapshot()
        self._assert_unchanged(originals)
        self.assertTrue(log.exists())
        for name in expected_workers:
            self.assertIn(f"Iniciando {name}", log.read_text())

        for mode, version, status in (
            ("no_drain_success", "2.0.999-fixture", "verified"),
            ("no_drain_fail_after_apply", "2.0.998-fixture", "rolled_back"),
        ):
            with self.subTest(mode=mode):
                fixture = MainPathRehearsalTest(
                    "test_disposable_no_drain_actual_main_success_preserves_data_and_never_drains")
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                fixture.prepare_no_drain_fixture()
                result = main_rehearsal(fixture.root, mode)
                self.assertEqual(
                    result.returncode,
                    0 if mode == "no_drain_success" else 2,
                    result.stderr[-900:] + result.stdout[-900:],
                )
                self.assertEqual(
                    (fixture.installed / "version").read_text().strip(), version)
                receipt = json.loads((
                    fixture.root /
                    "dsm928-composite-journal/game-uptime-transaction.json"
                ).read_text())
                self.assertEqual(receipt["status"], status)
                self.assertFalse(receipt["live_no_drain_authorized"])
                self.assertEqual(fixture.world.read_bytes(),
                                 b"saved-world-private-test")
                self.assertEqual(fixture.upload.read_bytes(),
                                 b"in-flight-upload-private-test")
                self.assertFalse((fixture.root / "steps").exists())
                self.assertEqual(self._snapshot(unit), before)
                self._assert_unchanged(originals)

        # Prove a REAL child of the transient supervisor can trigger the
        # production shell's wait -n -> exit 1 -> systemd Restart=on-failure.
        # Never send a signal to a PID without private script and cgroup proof.
        candidate = None
        for pid in children:
            proc = Path("/proc") / str(pid)
            try:
                command = (proc / "cmdline").read_bytes()
                cgroup = (proc / "cgroup").read_text()
            except OSError:
                continue
            if (str(workers / "automation_worker.py").encode() in command
                and unit in cgroup):
                candidate = pid
                break
        self.assertIsNotNone(candidate, "no verified disposable child to terminate")
        os.kill(candidate, signal.SIGTERM)
        after, recreated_children = running_snapshot(exclude_pid=before["pid"])
        self.assertNotEqual(before["pid"], after["pid"])
        self.assertEqual(len(recreated_children), len(expected_workers))
        self.assertIn("Worker filho encerrou inesperadamente", log.read_text())
        self._assert_unchanged(originals)
        self.assertFalse((fake_root / "config" / "agent.conf").exists())

    def test_two_real_systemd_processes_survive_actual_updater_file_functions(self):
        """Run actual update.sh backup/staging/apply/rollback on fake /tmp install."""
        originals = [self._start("real-alpha"), self._start("real-beta")]
        fake = self.workspace/"real-update-fixture"
        create_tiny_release_fixture(fake)

        def run(mode):
            completed = run_real_update_fns(fake, mode)
            if completed.returncode:
                raise RuntimeError(
                    f"real update.sh {mode} function failed: "
                    +completed.stderr[-350:]
                )

        run("prepare")
        journal = self.workspace/"real-update-journal"
        journal.mkdir(mode=0o700)

        outcome = transaction.execute(
            journal,
            [unit["unit"] for unit in originals],
            inspect=self._snapshot,
            apply=lambda: run("apply"),
            rollback=lambda: run("rollback"),
        )
        self.assertEqual(outcome["status"], "verified")
        self.assertFalse(outcome["live_no_drain_authorized"])
        self.assertEqual((fake/"installed/version").read_text(), "2.0.999-fixture")
        self.assertEqual(
            (fake/"installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat").read_bytes(),
            b"saved-world-private-test",
        )
        self._assert_unchanged(originals)

        # Rehearse the real update.sh rollback, still leaving systemd PIDs intact.
        run("rollback")
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")
        self._assert_unchanged(originals)

        def fail_after_real_file_replacement():
            run("apply")
            raise RuntimeError("fault injected after actual update.sh apply")

        failure_journal = self.workspace/"real-update-failure-journal"
        failure_journal.mkdir(mode=0o700)
        with self.assertRaisesRegex(transaction.TransactionSafetyError, "rollback completed"):
            transaction.execute(
                failure_journal,
                [unit["unit"] for unit in originals],
                inspect=self._snapshot,
                apply=fail_after_real_file_replacement,
                rollback=lambda: run("rollback"),
            )
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")
        self._assert_unchanged(originals)
        with (failure_journal/"game-uptime-transaction.json").open() as f:
            self.assertEqual(json.load(f)["status"], "rolled_back")

    def test_two_transient_game_processes_survive_isolated_change_and_rollback(self):
        originals = [self._start("alpha"), self._start("beta")]
        installed = self.workspace/"installed"
        target = self.workspace/"target"
        installed.mkdir(mode=0o700)  # Also used as the private transaction journal.
        target.mkdir()
        for root, value in ((installed,"original"),(target,"updated")):
            path = root/"dashboard/web/status.js"
            path.parent.mkdir(parents=True)
            path.write_text(value)

        impact = plan.analyze(installed,target)
        self.assertEqual(impact["classification"],"review_only")
        self.assertFalse(impact["live_no_drain_authorized"])
        # Exercise the reusable transaction journal and PID invariants, not
        # the production update.sh (which still drains all game instances).
        snapshot = installed/"dashboard/web/status.js"

        def write_content(content):
            temp = snapshot.with_name(snapshot.name+".candidate")
            temp.write_text(content)
            os.replace(temp, snapshot)

        completed = transaction.execute(
            self.workspace/"installed",
            [unit["unit"] for unit in originals],
            inspect=lambda unit: self._snapshot(unit),
            apply=lambda: write_content("updated"),
            rollback=lambda: write_content("original"),
        )
        self.assertEqual(completed["status"], "verified")
        self.assertFalse(completed["live_no_drain_authorized"])
        self.assertEqual(snapshot.read_text(), "updated")
        self._assert_unchanged(originals)

        # An apply failure must roll back the modified files, while both
        # disposable units preserve PID and start-time identity.
        rollback_stage = self.workspace/"rollback-fixture"
        rollback_stage.mkdir(mode=0o700)

        def failed_change():
            write_content("bad-candidate")
            raise ValueError("simulated update failure")

        with self.assertRaisesRegex(transaction.TransactionSafetyError, "rollback completed"):
            transaction.execute(
                rollback_stage,
                [unit["unit"] for unit in originals],
                inspect=lambda unit: self._snapshot(unit),
                apply=failed_change,
                rollback=lambda: write_content("original"),
            )
        self.assertEqual(snapshot.read_text(), "original")
        self._assert_unchanged(originals)
        recorded = json.loads((rollback_stage/"game-uptime-transaction.json").read_text())
        self.assertEqual(recorded["status"], "rolled_back")

        # Unknown runtime change never becomes an authorized no-drain update.
        runtime = installed/"agents/linux/runtime/worker.py"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("before")
        candidate = target/"agents/linux/runtime/worker.py"
        candidate.parent.mkdir(parents=True)
        candidate.write_text("after")
        impact = plan.analyze(installed,target)
        self.assertTrue(impact["requires_game_drain"])
        self.assertFalse(impact["live_no_drain_authorized"])
        self._assert_unchanged(originals)

    def test_pinned_minecraft_console_supervisor_survives_fixture_apply_and_rollback(self):
        """Run the real console supervisor from a versioned path under transient systemd."""
        import hashlib
        import socket
        import sys
        source = ROOT/"agents/linux/runtime/console_supervisor.py"
        stage_loader = SourceFileLoader(
            "dsm928_supervisor_stage_systemd",
            str(ROOT/"update-manager/game-uptime-supervisor-stage.py"),
        )
        stage_spec = importlib.util.spec_from_loader(stage_loader.name, stage_loader)
        stage_module = importlib.util.module_from_spec(stage_spec)
        stage_loader.exec_module(stage_module)
        versions = self.workspace/"pinned-supervisors"
        versions.mkdir(mode=0o700)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        staged = stage_module.stage_supervisor(source, versions, expected_sha256=digest)
        pinned = Path(staged["path"])
        self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(), digest)
        self.assertFalse(staged["live_no_drain_authorized"])
        sock_path = self.workspace/"minecraft-console.sock"
        unit = f"{self.prefix}-pinned-minecraft.service"
        self._run("systemd-run", "--unit", unit[:-8], "--collect",
                  "--property=Type=simple", sys.executable, str(pinned),
                  "--socket", str(sock_path), "--", "/usr/bin/sleep", "180")
        self.units.append(unit)
        for _ in range(50):
            snap = self._snapshot(unit)
            if snap["state"] == "active" and snap["pid"] > 1 and snap["started"] > 0 and sock_path.is_socket():
                break
            time.sleep(0.1)
        else:
            self.fail("disposable versioned console supervisor did not start")
        original = self._snapshot(unit)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(str(sock_path))
            client.sendall(b"status\n")
            self.assertEqual(client.recv(128), b"OK\n")
        self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(), digest)
        fake = self.workspace/"pinned-updater-fixture"
        create_tiny_release_fixture(fake)
        for phase in ("prepare", "apply", "rollback"):
            result = run_real_update_fns(fake, phase)
            self.assertEqual(result.returncode, 0, result.stderr[-800:])
            self.assertEqual(self._snapshot(unit), original)
            self.assertTrue(sock_path.is_socket())
            self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(), digest)
        self.assertFalse(staged["systemd_integrated"])
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")


    def test_controller_http_surrogate_restarts_while_pinned_supervisor_survives_rollback(self):
        """Isolated HTTP control-plane *surrogate* restart + real file rollback.

        Exercises the real console_supervisor.py and update.sh file functions,
        NOT the real DSM Controller, real Minecraft JVM or no-drain main().
        """
        import hashlib
        import socket
        import sys
        from urllib.request import urlopen
        from urllib.error import URLError

        source = ROOT/"agents/linux/runtime/console_supervisor.py"
        loader = SourceFileLoader("dsm928_supervisor_stage_control_restart",
                                  str(ROOT/"update-manager/game-uptime-supervisor-stage.py"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        stage = importlib.util.module_from_spec(spec)
        loader.exec_module(stage)
        versions = self.workspace/"control-restart-pinned"
        versions.mkdir(mode=0o700)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        pinned = Path(stage.stage_supervisor(source, versions, expected_sha256=digest)["path"])
        sock = self.workspace/"stable-console.sock"
        game_unit = f"{self.prefix}-stable-game.service"
        self._run("systemd-run", "--unit", game_unit[:-8], "--collect",
                  "--property=Type=simple", sys.executable, str(pinned),
                  "--socket", str(sock), "--", "/usr/bin/sleep", "180")
        self.units.append(game_unit)
        for _ in range(60):
            prior = self._snapshot(game_unit)
            if prior["state"] == "active" and prior["pid"] > 1 and prior["started"] > 0 and sock.is_socket():
                break
            time.sleep(0.1)
        else:
            self.fail("pinned game supervisor failed to become ready")

        def check_game():
            self.assertEqual(self._snapshot(game_unit), prior)
            self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(), digest)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect(str(sock))
                client.sendall(b"status\n")
                self.assertEqual(client.recv(32), b"OK\n")

        # Only a tiny, owner-marked test installation under /tmp is modified.
        fake = self.workspace/"control-restart-release-fixture"
        create_tiny_release_fixture(fake)
        web_root = fake/"installed/dashboard/web"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as bound:
            bound.bind(("127.0.0.1", 0))
            port = bound.getsockname()[1]
        url = "http://127.0.0.1:%d/presentation.js" % port

        def controller_start(suffix):
            name = f"{self.prefix}-http-{suffix}.service"
            self._run("systemd-run", "--unit", name[:-8], "--collect",
                      "--property=Type=simple",
                      sys.executable, "-m", "http.server", str(port),
                      "--bind", "127.0.0.1", "--directory", str(web_root))
            self.units.append(name)
            return name

        def content(expected):
            for _ in range(60):
                try:
                    with urlopen(url, timeout=1) as response:
                        body = response.read().decode("utf-8")
                    if body == expected:
                        return
                except (URLError, TimeoutError, OSError):
                    pass
                time.sleep(0.1)
            self.fail("disposable HTTP controller surrogate did not serve " + expected)

        def update_step(step):
            completed = run_real_update_fns(fake, step)
            if completed.returncode != 0:
                raise RuntimeError("fixture " + step + " failed: " + completed.stderr[-350:])

        controller_old = controller_start("old")
        content("from-2.0.998-fixture")
        check_game()
        update_step("prepare")
        journal = self.workspace/"control-restart-journal"
        journal.mkdir(mode=0o700)
        controller_new = [None]
        controller_restored = [None]

        def update_then_inject_failure():
            self._run("systemctl", "stop", controller_old)
            check_game()
            update_step("apply")
            check_game()
            controller_new[0] = controller_start("new")
            content("from-2.0.999-fixture")
            check_game()
            raise RuntimeError("injected failure after disposable Controller restart")

        def compensate():
            if controller_new[0] is not None:
                self._run("systemctl", "stop", controller_new[0])
            update_step("rollback")
            controller_restored[0] = controller_start("restored")
            content("from-2.0.998-fixture")
            check_game()

        with self.assertRaisesRegex(transaction.TransactionSafetyError, "rollback completed"):
            transaction.execute(journal, [game_unit], inspect=self._snapshot,
                                apply=update_then_inject_failure,
                                rollback=compensate)
        check_game()
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")
        self.assertEqual((fake/"installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat").read_bytes(),
                         b"saved-world-private-test")
        self.assertEqual((fake/"installed/data/database.txt").read_text(), "db durable")
        self.assertEqual(json.loads((journal/"game-uptime-transaction.json").read_text())["status"],
                         "rolled_back")
        self.assertIsNotNone(controller_restored[0])


    def test_disposable_systemd_pids_survive_interrupted_apply_and_operator_rollback(self):
        """Recover a partial file transaction with real transient systemd PIDs.

        The crash here is SystemExit. A separate unit test uses actual SIGKILL.
        """
        originals = [self._start("recovery-alpha"), self._start("recovery-beta")]
        fake = self.workspace/"recovery-real-updater-functions"
        fake.mkdir(mode=0o700)
        create_tiny_release_fixture(fake)
        # Model the real DSM installation: product files are owned by a
        # non-root service user, while the journal workspace stays root-only.
        import pwd
        product = pwd.getpwnam("nobody")
        product_identity = (product.pw_uid, product.pw_gid)
        for path in (fake/"installed", fake/"installed/dashboard",
                     fake/"installed/dashboard/web", fake/"installed/version",
                     fake/"installed/dashboard/web/presentation.js"):
            os.chown(path, *product_identity)
        protected = [fake/"installed", fake/"installed/runtime/hybrid-instance-storage",
                     fake/"installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat",
                     fake/"installed/data/database.txt", fake/"installed/config/dsm.conf"]
        original_inodes = {p: p.stat().st_ino for p in protected}
        interrupt_after_apply = [False]
        journal = self.workspace/"interrupted-real-systemd-journal"
        journal.mkdir(mode=0o700)

        # Reuse the existing local lease and real kernel inodes throughout
        # both the interrupted apply and the reviewed recovery rollback.
        import hashlib
        import fcntl
        scope_loader = SourceFileLoader("dsm928_recovery_bound_scope",
            str(ROOT / "update-manager/game-uptime-local-scope-lease.py"))
        scope_spec = importlib.util.spec_from_loader(scope_loader.name, scope_loader)
        scope = importlib.util.module_from_spec(scope_spec)
        scope_loader.exec_module(scope)
        scope_root = self.workspace / "recovery-local-scope"
        scope_root.mkdir(mode=0o700)
        (scope_root / "fixture-owner").write_bytes(b"DSM928_DISPOSABLE_FIXTURE_V1\n")
        parent = scope_root / "runtime"
        runtime = parent / "run"
        workers = runtime / "worker-operations"
        state = scope_root / "state"
        for folder in (parent, runtime, workers, state):
            folder.mkdir(mode=0o755)
        controller = runtime / "controller-agent-http.lock"
        helper = runtime / "agent-privileged-operations.lock"
        child = runtime / "agent-finalization-operations.lock"
        locks = [controller, helper, child] + [workers / (name + ".lock")
                                                for name in scope.WORKERS]
        for lock in locks:
            lock.touch(mode=0o600)
            lock.chmod(0o660 if lock == child else 0o600)
        hybrid_id = "fixture-agent-hybrid"
        remote_ids = ["fixture-agent-alpha", "fixture-agent-beta"]
        agent_ids = [hybrid_id, *remote_ids]
        opts = dict(transaction_id=uuid4().hex, release_sha256="a"*64,
                    expected_controller_uid=os.geteuid(),
                    expected_worker_uid=os.geteuid(), controller_lock=controller,
                    worker_lock_dir=workers, hold_path=runtime/"hold.json",
                    pending_path=state/"no-drain-pending.json", fixture_root=scope_root,
                    prepare_fresh_fixture=True, expected_fixture_agent_ids=agent_ids)
        # The original interrupted systemd apply now also retains two
        # Agent scopes over the real session protocol (local sockets only).
        import sys
        import socket
        import threading
        from contextlib import contextmanager
        agent_runtime = str(ROOT / "agents/linux/runtime")
        sys.path.insert(0, agent_runtime)
        try:
            from game_uptime_hold_coordinator import (
                prepare_standalone_agent_scope, serve_prepared_agent_session,
            )
        finally:
            sys.path.remove(agent_runtime)
        channels = {}
        remote_locks = []
        remote_errors = []
        for index, agent in enumerate(remote_ids):
            host = self.workspace / ("recovery-agent-" + str(index))
            host.mkdir(mode=0o755)
            host.chmod(0o755)
            host_run, host_state = host / "run", host / "state"
            for directory in (host_run, host_state):
                directory.mkdir(mode=0o755)
                directory.chmod(0o755)
            priv = host_run / "agent-privileged-operations.lock"
            final = host_run / "agent-finalization-operations.lock"
            for inode in (priv, final):
                inode.touch(mode=0o600)
                inode.chmod(0o660 if inode == final else 0o600)
            remote_locks.extend((priv, final))
            remote_options = dict(hold_path=host_run/"hold.json",
                                  journal_path=host_state/"no-drain-pending.json",
                                  privileged_lock_path=priv, finalization_lock_path=final,
                                  trusted_uid=os.geteuid(), fixture_root=host,
                                  fixture_group_gid=os.getegid())
            def make_opener(agent, remote_options):
                @contextmanager
                def opened():
                    client, server = socket.socketpair()
                    def serve():
                        try:
                            def factory(**shared):
                                return prepare_standalone_agent_scope(**remote_options, **shared)
                            serve_prepared_agent_session(
                                server.fileno(), server.fileno(), local_agent_id=agent,
                                scope_factory=factory, now=time.time)
                        except Exception as exc:
                            # EOF is expected after a simulated interruption.
                            remote_errors.append(str(exc))
                        finally:
                            server.close()
                    thread = threading.Thread(target=serve, daemon=True)
                    thread.start()
                    try:
                        yield (client.fileno(), client.fileno())
                    finally:
                        client.close()
                        thread.join(timeout=5)
                        self.assertFalse(thread.is_alive())
                return opened
            channels[agent] = make_opener(agent, remote_options)
        locks.extend(remote_locks)
        def inspect_game(name):
            if (interrupt_after_apply[0] and
                    (fake/"installed/version").read_text() == "2.0.999-fixture"):
                interrupt_after_apply[0] = False
                assert_locks()
                self._assert_unchanged(originals)
                raise SystemExit(47)
            result = self._snapshot(name)
            result["unit_config_sha256"] = hashlib.sha256(
                self._run("systemctl", "cat", name).stdout.encode()).hexdigest()
            return result
        def list_games():
            return [line.split()[0] for line in self._run(
                "systemctl", "list-units", "--type=service", "--state=active",
                "--no-legend", "--plain", f"{self.prefix}-*.service").stdout.splitlines()
                if line.strip()]
        names = [row["unit"] for row in originals]
        handoff = transaction.attest_handoff(names, inspect=inspect_game, list_units=list_games)
        def assert_locks():
            for lock in locks:
                fd = os.open(lock, os.O_RDONLY)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(fd)
        # Reject omitted/misclassified members before any durable evidence.
        with self.assertRaisesRegex(transaction.TransactionSafetyError, "inventory incomplete"):
            transaction.execute(
                journal, names, inspect=inspect_game, list_units=list_games,
                handoff=handoff, local_scope_kwargs=opts,
                distributed_fixture_openers=channels,
                apply=lambda: self.fail("incomplete partition applied"),
                rollback=lambda: self.fail("unexpected rollback"))
        self.assertFalse(opts["pending_path"].exists())
        interrupt_after_apply[0] = True
        with self.assertRaises(SystemExit):
            transaction.execute(
                journal,
                [row["unit"] for row in originals],
                inspect=inspect_game, list_units=list_games, handoff=handoff,
                local_scope_kwargs=opts,
                local_fixture_agent_id=hybrid_id,
                distributed_fixture_openers=channels,
                file_transaction_workspace=fake, file_transaction_identity=product_identity,
                file_transaction_paths=["dashboard/web/presentation.js", "version"],
            )
        self.assertEqual((fake/"installed/version").read_text(), "2.0.999-fixture")
        recorded = json.loads((journal/"game-uptime-transaction.json").read_text())
        self.assertEqual(recorded["status"], "applied")
        binding = recorded["local_scope_binding"]
        file_journal = fake/"dsm928-product-files.json"
        self.assertEqual(file_journal.stat().st_uid, 0)
        self.assertEqual(file_journal.stat().st_mode & 0o777, 0o600)
        self.assertEqual((fake/"installed/version").stat().st_uid, product_identity[0])
        self.assertEqual(binding["product_file_binding"]["journal_sha256"],
                         hashlib.sha256(file_journal.read_bytes()).hexdigest())
        self.assertEqual({p: p.stat().st_ino for p in protected}, original_inodes)
        self.assertEqual(binding["agent_ids"], sorted(agent_ids))
        self.assertEqual(binding["distributed_scope_binding"]["agent_ids"],
                         sorted(remote_ids))
        self.assertEqual(binding["distributed_scope_binding"]["local_hybrid_agent_id"], hybrid_id)
        for index in range(len(remote_ids)):
            inventory = json.loads((self.workspace / ("recovery-agent-" + str(index))
                / "state/no-drain-agent-inventory.json").read_text())
            self.assertEqual(inventory["agent_ids"], sorted(agent_ids))
        self.assertEqual(remote_errors, ["agent_session_disconnected"] * len(remote_ids))
        remote_errors.clear()
        self._assert_unchanged(originals)

        with self.assertRaisesRegex(transaction.TransactionSafetyError, "scope binding mismatch"):
            transaction.recover_interrupted(
                journal, names, inspect=inspect_game, list_units=list_games,
                rollback=lambda: self.fail("unbound rollback"), operator_reviewed=True)
        recovery_opts = {**opts, "prepare_fresh_fixture": False,
                         "expected_fixture_agent_ids": None,
                         "inspect_existing_prepared": True,
                         "expected_recovery_agent_ids": agent_ids}
        with self.assertRaisesRegex(transaction.TransactionSafetyError, "scope binding mismatch"):
            transaction.recover_interrupted(
                journal, names, inspect=inspect_game, list_units=list_games,
                rollback=lambda: self.fail("remote scope omitted"), operator_reviewed=True,
                local_scope_kwargs=recovery_opts)
        outcome = transaction.recover_interrupted(
            journal, names, inspect=inspect_game, list_units=list_games,
            file_transaction_workspace=fake, file_transaction_identity=product_identity, operator_reviewed=True,
            local_scope_kwargs=recovery_opts, distributed_fixture_openers=channels,
            local_fixture_agent_id=hybrid_id,
        )
        self.assertEqual(remote_errors, [])
        self.assertEqual(outcome["status"], "recovered_rollback")
        self.assertFalse(outcome["live_no_drain_authorized"])
        terminal_hash = hashlib.sha256((journal/"game-uptime-transaction.json").read_bytes()).hexdigest()
        for index in range(len(remote_ids)):
            state = self.workspace / ("recovery-agent-" + str(index)) / "state"
            terminal = json.loads((state / ("terminal-" + opts["transaction_id"] + ".json")).read_bytes())
            self.assertEqual(terminal["outcome"], "recovered_rollback")
            self.assertEqual(terminal["journal_sha256"], terminal_hash)
            self.assertTrue((state/"no-drain-pending.json").exists())
        confirmation = journal / "game-uptime-terminal-confirmation.json"
        confirmed = json.loads(confirmation.read_bytes())
        self.assertEqual(confirmed["journal_sha256"], terminal_hash)
        self.assertEqual(confirmed["recorded_agent_ids"], sorted(remote_ids))
        self.assertTrue(confirmed["pending_evidence_retained"])
        saved_confirmation = (confirmation.stat().st_ino, confirmation.read_bytes())
        retried = transaction.confirm_terminal(
            journal, names, inspect=inspect_game, list_units=list_games,
            operator_reviewed=True, local_scope_kwargs=recovery_opts,
            distributed_fixture_openers=channels, local_fixture_agent_id=hybrid_id,
            file_transaction_workspace=fake, file_transaction_identity=product_identity)
        self.assertTrue(retried["terminal_confirmation_retried"])
        self.assertEqual(saved_confirmation, (confirmation.stat().st_ino, confirmation.read_bytes()))
        self.assertEqual(remote_errors, [])
        finalized = transaction.confirm_terminal(
            journal, names, inspect=inspect_game, list_units=list_games,
            operator_reviewed=True, local_scope_kwargs=recovery_opts,
            distributed_fixture_openers=channels, local_fixture_agent_id=hybrid_id,
            finalize_fixture=True, file_transaction_workspace=fake, file_transaction_identity=product_identity)
        self.assertTrue(finalized["fixture_hold_released"])
        self.assertEqual(remote_errors, [])
        self.assertFalse(opts["pending_path"].exists())
        self.assertFalse(opts["hold_path"].exists())
        states = [opts["pending_path"].parent]
        states.extend(self.workspace / ("recovery-agent-" + str(i)) / "state"
                      for i in range(len(remote_ids)))
        for folder in states:
            self.assertFalse((folder/"no-drain-pending.json").exists())
            archive = json.loads((folder / ("released-" + opts["transaction_id"] + ".json")).read_bytes())
            self.assertEqual(archive["journal_sha256"], terminal_hash)
            self.assertIn("no-drain-pending.json", archive["evidence"])
        self.assertTrue((journal/"game-uptime-fixture-release.json").exists())
        self.assertEqual((fake/"installed/version").read_text(), "2.0.998-fixture")
        self.assertEqual((fake/"installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat").read_bytes(),
                         b"saved-world-private-test")
        self.assertEqual((fake/"installed/data/database.txt").read_text(), "db durable")
        self.assertEqual(json.loads((journal/"game-uptime-transaction.json").read_text())["status"],
                         "recovered_rollback")
        self.assertEqual({p: p.stat().st_ino for p in protected}, original_inodes)
        self._assert_unchanged(originals)


    def test_minecraft_supervisor_and_dayz_udp_standin_survive_apply_and_rollback(self):
        """Two distinct disposable game-shaped units remain responsive.

        Minecraft uses actual SHA-pinned console_supervisor.py with a sleep
        child (not a Minecraft JVM). DayZ uses a UDP echo stand-in (not DayZ).
        updater functions operate exclusively on an owned /tmp fixture.
        """
        import hashlib
        import socket
        import sys

        source = ROOT / "agents/linux/runtime/console_supervisor.py"
        loader = SourceFileLoader(
            "dsm928_supervisor_stage_dual_game",
            str(ROOT / "update-manager/game-uptime-supervisor-stage.py"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        stage = importlib.util.module_from_spec(spec)
        loader.exec_module(stage)
        versions = self.workspace / "dual-game-pinned-versions"
        versions.mkdir(mode=0o700)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        staged = stage.stage_supervisor(
            source, versions, expected_sha256=digest)
        pinned = Path(staged["path"])
        self.assertFalse(staged["live_no_drain_authorized"])

        minecraft_sock = self.workspace / "dual-game-console.sock"
        minecraft_unit = f"{self.prefix}-minecraft-pinned.service"
        self._run(
            "systemd-run", "--unit", minecraft_unit[:-8], "--collect",
            "--property=Type=simple", sys.executable, str(pinned),
            "--socket", str(minecraft_sock), "--", "/usr/bin/sleep", "180",
        )
        self.units.append(minecraft_unit)

        dayz_script = self.workspace / "dayz-udp-standin.py"
        dayz_script.write_text(
            "import socket,sys\n"
            "sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)\n"
            "sock.bind(('127.0.0.1',int(sys.argv[1])))\n"
            "while True:\n"
            " data,peer=sock.recvfrom(4096)\n"
            " if data==b'dayz-fixture-query':\n"
            "  sock.sendto(b'dayz-fixture-ok',peer)\n",
            encoding="utf-8",
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as reserve:
            reserve.bind(("127.0.0.1", 0))
            dayz_port = reserve.getsockname()[1]
        dayz_unit = f"{self.prefix}-dayz-udp.service"
        self._run(
            "systemd-run", "--unit", dayz_unit[:-8], "--collect",
            "--property=Type=simple", sys.executable, str(dayz_script),
            str(dayz_port),
        )
        self.units.append(dayz_unit)

        def query_dayz():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(0.5)
                client.sendto(b"dayz-fixture-query", ("127.0.0.1", dayz_port))
                return client.recvfrom(128)[0]

        for _ in range(60):
            minecraft = self._snapshot(minecraft_unit)
            dayz = self._snapshot(dayz_unit)
            ready = (
                minecraft["state"] == "active" and minecraft["pid"] > 1
                and minecraft["started"] > 0 and dayz["state"] == "active"
                and dayz["pid"] > 1 and dayz["started"] > 0
                and minecraft_sock.is_socket()
            )
            if ready:
                try:
                    if query_dayz() == b"dayz-fixture-ok":
                        break
                except (socket.timeout, OSError):
                    pass
            time.sleep(0.1)
        else:
            self.fail("disposable supervisor or UDP stand-in not ready")
        originals = [minecraft, dayz]

        # Verify the *complete* transient game-unit set, not just these
        # recorded PIDs. Derive an independent witness from real systemd
        # directives without persisting potentially sensitive ExecStart data.
        def list_active_game_standins():
            result = self._run(
                "systemctl", "list-units", "--all", "--type=service",
                "--state=active", "--plain", "--no-legend",
                "dsm928-e2e-*.service",
            )
            return [line.split()[0] for line in result.stdout.splitlines()
                    if line.strip() and line.split()[0].endswith(".service")]

        def systemd_witness(unit):
            result = self._snapshot(unit)
            properties = self._run(
                "systemctl", "show", unit,
                "-p", "ExecStart", "-p", "FragmentPath",
                "-p", "DropInPaths", "-p", "User", "-p", "WorkingDirectory",
                "-p", "PartOf", "-p", "BindsTo", "-p", "PropagatesStopTo",
            )
            result["unit_config_sha256"] = hashlib.sha256(
                properties.stdout.encode("utf-8")
            ).hexdigest()
            return result

        def check_both():
            self._assert_unchanged(originals)
            self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(),
                             digest)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect(str(minecraft_sock))
                client.sendall(b"status\n")
                self.assertEqual(client.recv(128), b"OK\n")
            self.assertEqual(query_dayz(), b"dayz-fixture-ok")

        def updater(workspace, phase):
            result = run_real_update_fns(workspace, phase)
            self.assertEqual(result.returncode, 0,
                             (phase, result.stdout[-500:], result.stderr[-700:]))

        check_both()
        for mode in ("success", "fault_after_apply"):
            with self.subTest(mode=mode):
                fixture = self.workspace / ("dual-game-" + mode)
                create_tiny_release_fixture(fixture)
                updater(fixture, "prepare")
                check_both()
                journal = self.workspace / ("dual-game-transaction-" + mode)
                journal.mkdir(mode=0o700)

                def apply():
                    updater(fixture, "apply")
                    self.assertEqual(
                        (fixture / "installed/version").read_text(),
                        "2.0.999-fixture",
                    )
                    check_both()
                    if mode == "fault_after_apply":
                        raise RuntimeError("injected after files swapped")

                def rollback():
                    updater(fixture, "rollback")
                    check_both()

                handoff = transaction.attest_handoff(
                    [minecraft_unit, dayz_unit], inspect=systemd_witness,
                    list_units=list_active_game_standins,
                )
                if mode == "success":
                    result = transaction.execute(
                        journal, [minecraft_unit, dayz_unit],
                        inspect=systemd_witness, apply=apply, rollback=rollback,
                        handoff=handoff, list_units=list_active_game_standins,
                    )
                    receipt = json.loads(
                        (journal / "game-uptime-transaction.json").read_text())
                    self.assertTrue(receipt["strict_inventory"])
                    self.assertEqual(len(receipt["original_units"]), 2)
                    self.assertEqual(len(receipt["original_units_sha256"]), 64)
                    self.assertEqual(result["status"], "verified")
                    self.assertEqual(
                        (fixture / "installed/version").read_text(),
                        "2.0.999-fixture",
                    )
                else:
                    with self.assertRaisesRegex(
                        transaction.TransactionSafetyError, "rollback completed"
                    ):
                        transaction.execute(
                            journal, [minecraft_unit, dayz_unit],
                            inspect=systemd_witness, apply=apply,
                            rollback=rollback, handoff=handoff,
                            list_units=list_active_game_standins,
                        )
                    self.assertEqual(
                        (fixture / "installed/version").read_text(),
                        "2.0.998-fixture",
                    )
                    self.assertEqual(
                        json.loads(
                            (journal / "game-uptime-transaction.json").read_text()
                        )["status"], "rolled_back",
                    )
                self.assertEqual(
                    (fixture /
                     "installed/runtime/hybrid-instance-storage/minecraft005/world/level.dat"
                     ).read_bytes(), b"saved-world-private-test",
                )
                self.assertEqual(
                    (fixture / "installed/data/database.txt").read_text(),
                    "db durable",
                )
                check_both()


    def test_pinned_minecraft_supervisor_runs_as_unprivileged_systemd_user(self):
        """Prove real service-user access to SHA-pinned code in a throwaway unit.

        A transient dsm928-e2e unit uses User=nobody and runs a console
        supervisor with /usr/bin/sleep as its child, NOT a Minecraft JVM.
        No Capivara game unit or host systemd materializer is modified.
        """
        import hashlib
        import pwd
        import socket
        import sys

        try:
            account = pwd.getpwnam("nobody")
        except KeyError:
            self.skipTest("disposable runner lacks nobody service account")
        if account.pw_uid == os.geteuid():
            self.skipTest("test requires distinct non-root service account")
        runtime = ROOT / "agents/linux/runtime"
        if str(runtime) not in sys.path:
            sys.path.insert(0, str(runtime))
        from materializers.base import MaterializerError
        from materializers.systemd import render_unit

        loader = SourceFileLoader(
            "dsm928_unprivileged_supervisor_stage",
            str(ROOT / "update-manager/game-uptime-supervisor-stage.py"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        stage = importlib.util.module_from_spec(spec)
        loader.exec_module(stage)

        source = runtime / "console_supervisor.py"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        versions = self.workspace / "pinned-versions-unprivileged"
        versions.mkdir(mode=0o755)
        versions.chmod(0o755)
        staged = stage.stage_supervisor(source, versions, expected_sha256=digest)
        pinned = Path(staged["path"])
        self.assertEqual(pinned.stat().st_mode & 0o777, 0o444)
        pin = {"path": str(pinned), "sha256": digest}
        runtime_spec = {
            "instance_id": "fixture-minecraft-nobody",
            "agent_id": "disposable-agent",
            "runtime_id": "minecraft.java.neoforge",
            "game_id": "minecraft",
            "environment_id": "minecraft.java.neoforge",
            "user": account.pw_name,
            "working_directory": str(self.workspace),
            "executable": "/usr/bin/sleep",
            "arguments": ["180"],
        }

        # A 0700 ancestor, although readable as root, must not pass preflight.
        with self.assertRaisesRegex(MaterializerError, "not traversable"):
            render_unit(runtime_spec, pinned_supervisor_preview=pin)
        self.workspace.chmod(0o711)
        proposed = render_unit(runtime_spec, pinned_supervisor_preview=pin)
        self.assertIn("User=" + account.pw_name, proposed)
        self.assertIn('ExecStart="/usr/bin/python3" "' + str(pinned) + '"',
                      proposed)
        self.assertFalse(staged["live_no_drain_authorized"])

        sock_dir = self.workspace / "nobody-console"
        sock_dir.mkdir(mode=0o700)
        os.chown(sock_dir, account.pw_uid, account.pw_gid)
        sock = sock_dir / "console.sock"
        unit = f"{self.prefix}-unprivileged-minecraft.service"
        self._run(
            "systemd-run", "--unit", unit[:-8], "--collect",
            "--property=Type=simple", "--property=User=" + account.pw_name,
            "--property=NoNewPrivileges=yes",
            sys.executable, str(pinned),
            "--socket", str(sock), "--", "/usr/bin/sleep", "180",
        )
        self.units.append(unit)

        for _ in range(80):
            identity = self._snapshot(unit)
            if (identity["state"] == "active" and identity["pid"] > 1
                    and identity["started"] > 0 and sock.is_socket()):
                break
            time.sleep(0.1)
        else:
            self.fail("non-root pinned supervisor failed to start/read staged file")

        properties = self._run("systemctl", "show", unit, "-p", "User",
                               "-p", "ExecStart")
        self.assertIn("User=" + account.pw_name, properties.stdout)
        self.assertIn(str(pinned), properties.stdout)
        status = Path("/proc") / str(identity["pid"]) / "status"
        uid_line = next(
            line for line in status.read_text().splitlines()
            if line.startswith("Uid:"))
        self.assertEqual(int(uid_line.split()[1]), account.pw_uid)

        def verify_running():
            self.assertEqual(self._snapshot(unit), identity)
            self.assertEqual(hashlib.sha256(pinned.read_bytes()).hexdigest(),
                             digest)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect(str(sock))
                client.sendall(b"status\n")
                self.assertEqual(client.recv(64), b"OK\n")

        verify_running()
        fixture = self.workspace / "unprivileged-pinned-updater-fixture"
        create_tiny_release_fixture(fixture)
        for phase in ("prepare", "apply", "rollback"):
            result = run_real_update_fns(fixture, phase)
            self.assertEqual(result.returncode, 0,
                             (phase, result.stderr[-450:]))
            verify_running()
        self.assertEqual(
            (fixture / "installed/version").read_text(),
            "2.0.998-fixture")


    def test_disposable_live_systemd_unit_file_swap_and_manual_restore_keep_pid(self):
        """Actually replace a /run/systemd/system unit in a clean CI runner.

        Only dsm928-e2e-* names with allowlisted /usr/bin/sleep commands
        qualify. No Capivara instance unit or update.sh is touched.
        """
        import hashlib

        loader = SourceFileLoader(
            "dsm928_file_swap_disposable_only",
            str(ROOT / "update-manager/game-uptime-systemd-swap.py"),
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        swap = importlib.util.module_from_spec(spec)
        loader.exec_module(swap)
        unit = f"{self.prefix}-file-swap.service"
        path = Path("/run/systemd/system") / unit
        marker = (
            "# DSM928_DISPOSABLE_UNIT_V1\n"
            f"# DSM928_UNIT={unit}\n"
            "[Unit]\nDescription=DSM928 isolated sleep test\n"
            "[Service]\nType=simple\n"
        )
        old = (marker + "ExecStart=/usr/bin/sleep 180\n").encode()
        new = (marker + "ExecStart=/usr/bin/sleep 170\n").encode()
        self.assertFalse(path.exists())
        self.assertFalse(path.is_symlink())
        journal = self.workspace / "real-systemd-unit-file-swap"
        journal.mkdir(mode=0o700)
        path.write_bytes(old)
        path.chmod(0o644)

        try:
            self._run("systemctl", "daemon-reload")
            self._run("systemctl", "start", unit)
            self.units.append(unit)
            for _ in range(50):
                baseline = self._snapshot(unit)
                if (baseline["state"] == "active" and baseline["pid"] > 1
                        and baseline["started"] > 0):
                    break
                time.sleep(0.1)
            else:
                self.fail("disposable unit did not become active")

            applied = swap.swap_unit(
                journal, unit, unit_dir=Path("/run/systemd/system"),
                candidate=new, expected_old_sha256=hashlib.sha256(old).hexdigest(),
                inspect=self._snapshot,
            )
            self.assertEqual(applied["status"], "applied")
            self.assertFalse(applied["live_no_drain_authorized"])
            self.assertEqual(path.read_bytes(), new)
            self.assertEqual(self._snapshot(unit), baseline)
            self.assertEqual(
                json.loads((journal / "dsm928-unit-swap.json").read_text())["status"],
                "applied",
            )
            shown = self._run("systemctl", "cat", unit)
            self.assertIn("ExecStart=/usr/bin/sleep 170", shown.stdout)
            restored = swap.restore_unit(
                journal, unit, unit_dir=Path("/run/systemd/system"),
                inspect=self._snapshot, operator_reviewed=True,
            )
            self.assertEqual(restored["status"], "restored")
            self.assertFalse(restored["live_no_drain_authorized"])
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(self._snapshot(unit), baseline)
            with self.assertRaises(swap.DisposableSwapError):
                swap.restore_unit(
                    journal, unit, unit_dir=Path("/run/systemd/system"),
                    inspect=self._snapshot, operator_reviewed=True,
                )
        finally:
            # Mandatory teardown of *this exact* disposable service only.
            subprocess.run(("systemctl", "stop", unit), timeout=15,
                           capture_output=True, text=True, check=False)
            if path.is_file() and not path.is_symlink():
                path.unlink()
            subprocess.run(("systemctl", "daemon-reload"), timeout=20,
                           capture_output=True, text=True, check=False)


    def test_actual_pinned_minecraft_supervisor_unit_swap_retains_old_live_revision(self):
        """Switch staged supervisor SHA in real disposable unit, no JVM/start.

        The currently running pinned Python console supervisor retains its
        original PID and /proc command line after daemon-reload. Unit files
        are restored before teardown, and both exact versions stay staged.
        """
        import hashlib
        import socket
        import sys

        stage_loader = SourceFileLoader(
            "dsm928_pinned_stage_systemd_swap",
            str(ROOT / "update-manager/game-uptime-supervisor-stage.py"))
        stage_spec = importlib.util.spec_from_loader(
            stage_loader.name, stage_loader)
        stage = importlib.util.module_from_spec(stage_spec)
        stage_loader.exec_module(stage)

        swap_loader = SourceFileLoader(
            "dsm928_pinned_systemd_swap_real_e2e",
            str(ROOT / "update-manager/game-uptime-systemd-swap.py"))
        swap_spec = importlib.util.spec_from_loader(
            swap_loader.name, swap_loader)
        swap = importlib.util.module_from_spec(swap_spec)
        swap_loader.exec_module(swap)

        journal = self.workspace / "pinned-real-file-swap"
        journal.mkdir(mode=0o700)
        versions = journal / "versions"
        versions.mkdir(mode=0o700)
        source = ROOT / "agents/linux/runtime/console_supervisor.py"
        v2_source = journal / "candidate-console-supervisor.py"
        v2_source.write_bytes(
            source.read_bytes() + b"\n# DSM928 disposable next revision\n")
        staged = []
        for source_file in (source, v2_source):
            digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
            result = stage.stage_supervisor(
                source_file, versions, expected_sha256=digest)
            staged.append(Path(result["path"]))
        self.assertNotEqual(staged[0], staged[1])

        sock = journal / "console.sock"
        unit = f"{self.prefix}-pinned-unit-swap.service"
        path = Path("/run/systemd/system") / unit
        header = (
            "# DSM928_DISPOSABLE_UNIT_V1\n"
            f"# DSM928_UNIT={unit}\n"
            "[Unit]\nDescription=DSM928 pinned supervisor test only\n"
            "[Service]\nType=simple\n"
        )
        def content(supervisor):
            return (header + "ExecStart=/usr/bin/python3 "
                    + str(supervisor) + " --socket " + str(sock)
                    + " -- /usr/bin/sleep 180\n").encode("utf-8")

        old, new = content(staged[0]), content(staged[1])
        self.assertFalse(path.exists())
        self.assertFalse(path.is_symlink())
        path.write_bytes(old)
        path.chmod(0o644)
        try:
            self._run("systemctl", "daemon-reload")
            self._run("systemctl", "start", unit)
            self.units.append(unit)
            for _ in range(70):
                identity = self._snapshot(unit)
                if (identity["state"] == "active" and identity["pid"] > 1
                        and identity["started"] > 0 and sock.is_socket()):
                    break
                time.sleep(0.1)
            else:
                self.fail("real pinned disposable supervisor did not start")

            cmdline = (Path("/proc") / str(identity["pid"]) /
                       "cmdline").read_bytes().split(b"\0")
            self.assertIn(os.fsencode(staged[0]), cmdline)
            self.assertNotIn(os.fsencode(staged[1]), cmdline)

            def check_live():
                self.assertEqual(self._snapshot(unit), identity)
                self.assertTrue(all(p.is_file() for p in staged))
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(3)
                    client.connect(str(sock))
                    client.sendall(b"status\n")
                    self.assertEqual(client.recv(64), b"OK\n")

            check_live()
            result = swap.swap_unit(
                journal, unit, unit_dir=Path("/run/systemd/system"),
                candidate=new,
                expected_old_sha256=hashlib.sha256(old).hexdigest(),
                inspect=self._snapshot,
            )
            self.assertEqual(result["status"], "applied")
            self.assertFalse(result["live_no_drain_authorized"])
            self.assertEqual(path.read_bytes(), new)
            self.assertIn(str(staged[1]),
                          self._run("systemctl", "cat", unit).stdout)
            # The unit is configured for a new supervisor only on a future
            # service start; the current old Python interpreter survives.
            self.assertIn(os.fsencode(staged[0]),
                          (Path("/proc") / str(identity["pid"]) /
                           "cmdline").read_bytes().split(b"\0"))
            check_live()

            restored = swap.restore_unit(
                journal, unit, unit_dir=Path("/run/systemd/system"),
                inspect=self._snapshot, operator_reviewed=True,
            )
            self.assertEqual(restored["status"], "restored")
            self.assertEqual(path.read_bytes(), old)
            self.assertIn(str(staged[0]),
                          self._run("systemctl", "cat", unit).stdout)
            check_live()
            self.assertEqual(
                json.loads((journal / "dsm928-unit-swap.json").read_text())["status"],
                "restored",
            )
            self.assertEqual(
                hashlib.sha256(staged[0].read_bytes()).hexdigest(),
                staged[0].name.removeprefix("console-supervisor-").removesuffix(".py"),
            )
            self.assertEqual(
                hashlib.sha256(staged[1].read_bytes()).hexdigest(),
                staged[1].name.removeprefix("console-supervisor-").removesuffix(".py"),
            )
        finally:
            # Never leave this disposable pinned service/unit on the runner.
            subprocess.run(
                ("systemctl", "stop", unit), capture_output=True,
                text=True, timeout=15, check=False,
            )
            if path.is_file() and not path.is_symlink():
                path.unlink()
            subprocess.run(
                ("systemctl", "daemon-reload"), capture_output=True,
                text=True, timeout=20, check=False,
            )

