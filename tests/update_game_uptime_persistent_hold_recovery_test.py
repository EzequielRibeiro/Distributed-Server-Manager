"""#928 Stage 2: one grouped root-journal/ephemeral-hold regression.

Disposable temporary paths only. No installed DSM, Agents, customer game
units, release pipeline or host service is modified.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
from game_uptime_maintenance_hold import observe
from game_uptime_hold_coordinator import (
    HoldPreparationBlocked,
    prepare_root_only,
)


class PersistentPendingHoldTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dsm928-pending-")
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        # tempfile defaults to 0700. Model the actual root-owned /run
        # parent traversal policy without weakening the runtime guard.
        base.chmod(0o755)
        self.state = base / "state"
        self.run = base / "run"
        self.state.mkdir(mode=0o755)
        self.run.mkdir(mode=0o755)
        self.journal = self.state / "no-drain-pending.json"
        self.marker = self.run / "no-drain-maintenance.json"
        self.uid = os.geteuid()
        self.tx = "1" * 32

    def prepare(self, **overrides):
        kwargs = {
            "transaction_id": self.tx, "ttl_seconds": 600,
            "journal_path": self.journal, "hold_path": self.marker,
            "trusted_uid": self.uid, "now": 1700000000,
        }
        kwargs.update(overrides)
        return prepare_root_only(**kwargs)

    def observation(self):
        return observe(path=self.marker, pending_path=self.journal,
                       trusted_uid=self.uid, now=1700000010)

    def test_durable_preparation_remains_negative_and_recovers_fail_closed(self):
        # A restrictive installer/systemd umask must not make the hold 0600.
        # Its JSON contains no credentials; Agent/Worker users need read only.
        previous_umask = os.umask(0o077)
        try:
            result = self.prepare()
        finally:
            os.umask(previous_umask)
        self.assertEqual(result["status"],
                         "persistent_hold_prepared_manual_recovery_required")
        self.assertFalse(result["live_no_drain_authorized"])
        self.assertFalse(result["remote_agents_acked"])
        journal = json.loads(self.journal.read_text())
        marker = json.loads(self.marker.read_text())
        self.assertEqual(journal["transaction_id"], marker["transaction_id"])
        self.assertEqual(journal["state"], "prepared_requires_distributed_fence")
        self.assertEqual(marker["kind"], "CapivaraDSMNoDrainMaintenanceHold")
        self.assertEqual(stat.S_IMODE(self.journal.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.marker.stat().st_mode), 0o644)
        self.assertEqual(self.marker.stat().st_uid, self.uid)
        self.assertEqual(self.journal.stat().st_uid, self.uid)
        self.assertFalse(self.marker.stat().st_mode & 0o022)
        with os.fdopen(os.open(self.marker, os.O_RDONLY | os.O_NOFOLLOW), "r") as stream:
            self.assertEqual(json.load(stream)["transaction_id"], self.tx)
        self.assertEqual(self.observation()["reason"], "root_owned_maintenance_hold")

        # Model a process crash/reboot removing only the /run marker. The
        # persistent pending inode MUST still block the next Worker tick.
        self.marker.unlink()
        self.assertEqual(self.observation(),
                         {"active": True,
                          "reason": "pending_journal_requires_operator_recovery"})
        with self.assertRaises(HoldPreparationBlocked):
            self.prepare()  # Never overwrite/replay without manual recovery.

    def test_root_release_binding_is_durable_operator_only_and_matches_hold(self):
        from game_uptime_transaction_binding import (
            ReleaseBindingBlocked, binding_for_hold, read_binding,
        )
        binding_path = self.state / "no-drain-release-binding.json"
        sha = "d" * 64
        from game_uptime_wire_replay_service import read_inventory
        ids = ["agent-B", "agent-A", "agent-offline"]
        with self.assertRaises(HoldPreparationBlocked):
            self.prepare(release_sha256=sha, binding_path=binding_path,
                         expected_agent_ids=["agent-A", "agent-A"])
        self.assertFalse(self.journal.exists())
        proof = self.prepare(
            release_sha256=sha, binding_path=binding_path,
            expected_agent_ids=ids)
        self.assertTrue(proof["release_identity_bound_locally"])
        self.assertTrue(proof["operator_agent_inventory_persisted"])
        inventory_path = self.state / "no-drain-agent-inventory.json"
        inventory = read_inventory(path=inventory_path, trusted_uid=self.uid)
        self.assertEqual(inventory["agent_ids"], sorted(ids))
        self.assertEqual(inventory["release_sha256"], sha)
        self.assertEqual(inventory["transaction_id"], self.tx)
        self.assertEqual(inventory["issued_at"], 1700000000)
        self.assertEqual(inventory["expires_at"], 1700000600)
        self.assertEqual(stat.S_IMODE(inventory_path.stat().st_mode), 0o600)
        original_inventory = inventory_path.read_bytes()
        self.assertFalse(proof["publisher_signature_verified"])
        self.assertFalse(proof["remote_agents_acked"])
        self.assertEqual(stat.S_IMODE(binding_path.stat().st_mode), 0o644)
        held = self.observation()
        checked = binding_for_hold(
            held, path=binding_path, now=1700000010, trusted_uid=self.uid)
        self.assertEqual(checked["release_sha256"], sha)
        self.assertEqual(checked["transaction_id"], self.tx)
        with self.assertRaises(ReleaseBindingBlocked):
            binding_for_hold(
                {**held, "transaction_id": "e" * 32},
                path=binding_path, now=1700000010, trusted_uid=self.uid)
        with self.assertRaises(ReleaseBindingBlocked):
            read_binding(path=binding_path, now=1700000700,
                         trusted_uid=self.uid)
        with self.assertRaises(HoldPreparationBlocked):
            self.prepare(release_sha256=sha, binding_path=binding_path)
        self.assertEqual(read_binding(
            path=binding_path, now=1700000010,
            trusted_uid=self.uid)["release_sha256"], sha)
        self.assertEqual(inventory_path.read_bytes(), original_inventory)
        # Tampered root evidence never downgrades into trusted release proof.
        binding_path.write_text(binding_path.read_text().replace(sha, "e"*63+"Z"))
        with self.assertRaises(ReleaseBindingBlocked):
            read_binding(path=binding_path, now=1700000010,
                         trusted_uid=self.uid)
        self.assertFalse(proof["live_no_drain_authorized"])

    def test_root_only_wire_nonce_journal_survives_restarts_without_ack(self):
        """One grouped replay/crash test on the existing disposable fixture."""
        from game_uptime_durable_wire_replay import (
            record_authenticated_negative_receipt,
        )
        import importlib
        import game_uptime_durable_wire_replay as replay_module

        sha = "a" * 64
        binding = self.state / "no-drain-release-binding.json"
        self.prepare(release_sha256=sha, binding_path=binding)
        receipts = self.state / "no-drain-wire-receipts"
        receipts.mkdir(mode=0o700)
        now = 1700000010
        def make_receipt(agent_id, nonce):
            return {
                "kind": "CapivaraNoDrainFenceEvidenceReceipt",
                "schema_version": 1, "agent_id": agent_id,
                "request_id": nonce, "transaction_id": self.tx,
                "release_sha256": sha, "issued_at": 1700000000,
                "expires_at": 1700000600,
                "contract": {
                    "protocol": "dsm928-fence-evidence-release-bound-readonly-v2",
                    "schema": "2",
                },
                "status": "authenticated_evidence_received_unfenced",
                "scope": "authenticated_heartbeat_wire_only",
                "agent_workers_fenced": False,
                "remote_agent_quiescence_acked": False,
                "live_no_drain_authorized": False,
            }
        scope = {
            "expected_agent_ids": ["agent-A", "agent-B"],
            "expected_transaction_id": self.tx,
            "expected_release_sha256": sha,
            "journal_dir": receipts, "hold_path": self.marker,
            "pending_path": self.journal, "binding_path": binding,
            "trusted_uid": self.uid, "now": now, "fixture_only": True,
        }
        nonce = "a" * 32
        first = make_receipt("agent-A", nonce)
        witness = record_authenticated_negative_receipt(
            authenticated_agent_id="agent-A", receipt=first, **scope)
        self.assertTrue(witness["wire_receipt_received"])
        self.assertFalse(witness["transport_authentication_independently_verified"])
        self.assertFalse(witness["remote_agent_quiescence_acked"])
        self.assertFalse(witness["live_no_drain_authorized"])
        record_path = receipts / (nonce + ".json")
        self.assertEqual(stat.S_IMODE(record_path.stat().st_mode), 0o600)
        original = record_path.read_bytes()
        # Re-import simulates a freshly booted coordinator: same disk nonce
        # cannot be accepted again, even under a different allowed Agent ID.
        importlib.reload(replay_module)
        with self.assertRaisesRegex(
                replay_module.DurableWireReplayBlocked,
                "replayed_or_existing_wire_nonce"):
            replay_module.record_authenticated_negative_receipt(
                authenticated_agent_id="agent-A", receipt=first, **scope)
        with self.assertRaisesRegex(
                replay_module.DurableWireReplayBlocked,
                "replayed_or_existing_wire_nonce"):
            replay_module.record_authenticated_negative_receipt(
                authenticated_agent_id="agent-B",
                receipt=make_receipt("agent-B", nonce), **scope)
        self.assertEqual(record_path.read_bytes(), original)
        # A new nonce is accepted only for a member of the fixed Agent set.
        with self.assertRaises(replay_module.DurableWireReplayBlocked):
            replay_module.record_authenticated_negative_receipt(
                authenticated_agent_id="unknown",
                receipt=make_receipt("unknown", "b" * 32), **scope)
        with self.assertRaises(replay_module.DurableWireReplayBlocked):
            replay_module.record_authenticated_negative_receipt(
                authenticated_agent_id="agent-B",
                receipt={**make_receipt("agent-B", "b"*32),
                         "release_sha256": "f"*64}, **scope)
        self.assertFalse((receipts / ("b"*32 + ".json")).exists())
        # Real socket writer's request parser + privileged append function:
        # one authenticated NEGATIVE record succeeds under a disposable root
        # journal; a duplicate request cannot be accepted after persistence.
        import game_uptime_wire_replay_service as wire_writer
        valid_wire = (json.dumps({
            "protocol": wire_writer.PROTOCOL,
            "authenticated_agent_id": "agent-B",
            "receipt": make_receipt("agent-B", "c"*32),
        }, sort_keys=True, separators=(",", ":")) + "\n").encode()
        def fixture_record(**kwargs):
            return replay_module.record_authenticated_negative_receipt(
                **kwargs, journal_dir=receipts, hold_path=self.marker,
                pending_path=self.journal, binding_path=binding,
                trusted_uid=self.uid, now=now, fixture_only=True)
        inventory_path = self.state / "no-drain-agent-inventory.json"
        inventory = {
            "kind": "DSM928OperatorAgentInventory", "schema_version": 1,
            "transaction_id": self.tx, "release_sha256": sha,
            "issued_at": 1700000000, "expires_at": 1700000600,
            "agent_ids": ["agent-A", "agent-B"],
        }
        def write_inventory(doc):
            inventory_path.write_text(json.dumps(
                doc, sort_keys=True, separators=(",", ":")) + "\n")
            inventory_path.chmod(0o600)

        def fixture_inventory():
            return wire_writer.read_inventory(
                path=inventory_path, trusted_uid=self.uid)

        def commit_wire():
            return wire_writer.commit_request(
                valid_wire, record_fn=fixture_record,
                inventory_fn=fixture_inventory)

        with self.assertRaises(wire_writer.RootWriterBlocked):
            commit_wire()
        for changed in ({"agent_ids": ["agent-A"]},
                        {"release_sha256": "f"*64},
                        {"agent_ids": ["agent-B", "agent-B"]}):
            write_inventory({**inventory, **changed})
            with self.assertRaises(wire_writer.RootWriterBlocked):
                commit_wire()
        write_inventory(inventory)
        def inspect_receipts():
            return wire_writer.inspect_persisted_receipts(
                journal_dir=receipts, hold_path=self.marker,
                pending_path=self.journal, binding_path=binding,
                trusted_uid=self.uid, now=now, fixture_only=True,
                expected_release_sha256=sha)
        before_coverage = inspect_receipts()
        self.assertEqual(before_coverage["missing_agent_ids"], ["agent-B"])
        self.assertFalse(before_coverage["wire_receipt_inventory_complete"])
        inventory_path.chmod(0o666)
        with self.assertRaises(wire_writer.RootWriterBlocked):
            commit_wire()
        inventory_path.chmod(0o600)
        self.assertFalse((receipts / ("c"*32 + ".json")).exists())
        recorded = commit_wire()
        self.assertEqual(recorded["status"],
                         "negative_v2_receipt_durably_recorded")
        self.assertFalse(recorded["remote_agent_quiescence_acked"])
        self.assertFalse(recorded["external_jobs_acked"])
        self.assertFalse(recorded["live_no_drain_authorized"])
        self.assertTrue((receipts / ("c"*32 + ".json")).exists())
        coverage = inspect_receipts()
        self.assertTrue(coverage["wire_receipt_inventory_complete"])
        self.assertEqual(coverage["observed_agent_count"], 2)
        self.assertFalse(coverage["remote_agents_acked"])
        self.assertFalse(coverage["live_no_drain_authorized"])
        # A registered offline Agent remains in the denominator.
        write_inventory({**inventory, "agent_ids": ["agent-A", "agent-B", "offline"]})
        self.assertEqual(inspect_receipts()["missing_agent_ids"], ["offline"])
        write_inventory(inventory)
        with self.assertRaises(replay_module.DurableWireReplayBlocked):
            commit_wire()
        with self.assertRaises(wire_writer.RootWriterBlocked):
            wire_writer.decode_request(
                valid_wire.replace(b'"protocol":', b'"protocol":"forged", "protocol":'))
        with self.assertRaises(wire_writer.RootWriterBlocked):
            wire_writer.decode_request(valid_wire + b"second\n")
        # SO_PEERCRED peer must match effective UID, installed Dashboard
        # interpreter and exact cgroup: a Worker using the same UID fails.
        fake_proc = self.run / "fixture-proc"
        pid_path = fake_proc / "31415"
        pid_path.mkdir(parents=True)
        (pid_path / "cgroup").write_text("0::/system.slice/dsm-dashboard.service\n")
        (pid_path / "cmdline").write_bytes(
            b"/usr/bin/python3\x00/opt/dsm/dashboard/server_part22.py\x00")
        (pid_path / "status").write_text("Uid:\t1001\t1001\t1001\t1001\n")
        self.assertTrue(wire_writer.peer_is_dashboard(
            pid=31415, uid=1001, expected_uid=1001, proc_root=fake_proc))
        self.assertFalse(wire_writer.peer_is_dashboard(
            pid=31415, uid=1002, expected_uid=1001, proc_root=fake_proc))
        (pid_path / "cgroup").write_text("0::/system.slice/dsm-dashboard-worker.service\n")
        self.assertFalse(wire_writer.peer_is_dashboard(
            pid=31415, uid=1001, expected_uid=1001, proc_root=fake_proc))
        # Loss of the ephemeral /run hold with durable pending journal
        # must block any new witness, without deleting historical evidence.
        self.marker.unlink()
        with self.assertRaises(replay_module.DurableWireReplayBlocked):
            replay_module.record_authenticated_negative_receipt(
                authenticated_agent_id="agent-B",
                receipt=make_receipt("agent-B", "b"*32), **scope)
        self.assertEqual(record_path.read_bytes(), original)
        self.assertFalse((receipts / ("b"*32 + ".json")).exists())

    def test_controller_startup_provisions_empty_storage_without_recovery(self):
        workers = str(ROOT / "dashboard/workers")
        sys.path.insert(0, workers)
        try:
            from prepare_maintenance_worker_locks import prepare_controller
        finally:
            sys.path.remove(workers)
        def prepare():
            return prepare_controller(
                self.uid, os.getegid(), runtime=self.run,
                state=self.state, parent_owner=self.uid)

        # Couple the installed service's opt-in with its root preparer.
        # Do not claim a local request lock proves distributed quiescence.
        unit = (ROOT / "systemd/dsm-dashboard.service").read_text()
        self.assertIn("Environment=DSM928_CONTROLLER_AGENT_HTTP_FLOCK=1\n", unit)
        self.assertIn("prepare_maintenance_worker_locks.py --user {{DSM_USER}} "
                      "--group {{DSM_GROUP}} --controller-only", unit)
        self.assertIn("ExecStart=/usr/bin/python3 /opt/dsm/dashboard/server_part22.py", unit)
        lock = prepare()
        self.assertEqual(lock.name, "controller-agent-http.lock")
        dashboard = str(ROOT / "dashboard")
        sys.path.insert(0, dashboard)
        try:
            from game_uptime_controller_agent_http_flock import (
                shared_controller_agent_http_lock,
                exclusive_controller_agent_http_lock,
                ControllerHttpLockUnavailable,
            )
        finally:
            sys.path.remove(dashboard)
        scope = dict(lock_path=lock, expected_uid=self.uid,
                     expected_gid=os.getegid(), parent_uid=self.uid)
        with shared_controller_agent_http_lock(**scope, enabled=True) as held:
            self.assertTrue(held)
            with self.assertRaises(ControllerHttpLockUnavailable):
                with exclusive_controller_agent_http_lock(**scope):
                    self.fail("exclusive lock acquired during HTTP mutation")
        with exclusive_controller_agent_http_lock(**scope) as observation:
            self.assertFalse(observation["live_no_drain_authorized"])
            with self.assertRaises(ControllerHttpLockUnavailable):
                with shared_controller_agent_http_lock(**scope, enabled=True):
                    self.fail("HTTP mutation admitted during exclusive lock")
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
        receipts = self.state / "no-drain-wire-receipts"
        self.assertEqual(stat.S_IMODE(receipts.stat().st_mode), 0o700)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.journal.exists())
        self.assertFalse((self.state / "no-drain-release-binding.json").exists())
        self.assertEqual(list(receipts.iterdir()), [])
        original = lock.stat().st_ino
        self.journal.write_bytes(b"interrupted")
        self.journal.chmod(0o600)
        self.assertEqual(prepare().stat().st_ino, original)
        self.assertEqual(self.journal.read_bytes(), b"interrupted")
        self.assertTrue(self.observation()["active"])
        lock.chmod(0o666)
        with self.assertRaises(RuntimeError):
            prepare()
        self.assertEqual(lock.stat().st_ino, original)
        self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o666)

    def test_partial_journal_blocks_after_crash_before_marker_write(self):
        self.journal.write_bytes(b"{incomplete")
        self.journal.chmod(0o600)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.observation()["reason"],
                         "pending_journal_requires_operator_recovery")

    def test_invalid_lease_and_transaction_never_create_files(self):
        for changes in (
            {"transaction_id": "../bad"},
            {"transaction_id": "f" * 31},
            {"ttl_seconds": 0},
            {"ttl_seconds": 901},
            {"ttl_seconds": True},
            {"now": -1},
        ):
            with self.subTest(changes=changes), self.assertRaises(HoldPreparationBlocked):
                self.prepare(**changes)
        self.assertFalse(self.journal.exists())
        self.assertFalse(self.marker.exists())

    def test_symlink_or_writable_parent_cannot_start_transaction(self):
        external = self.state / "outside"
        external.write_text("do not overwrite")
        self.journal.symlink_to(external)
        with self.assertRaises(HoldPreparationBlocked):
            self.prepare()
        self.assertEqual(external.read_text(), "do not overwrite")
        self.assertFalse(self.marker.exists())
        self.journal.unlink()
        self.state.chmod(0o777)
        try:
            with self.assertRaises(HoldPreparationBlocked):
                self.prepare()
            self.assertFalse(self.journal.exists())
        finally:
            self.state.chmod(0o755)
        # The journal folder may remain root-private; the /run marker path
        # must be traversable by an Agent running under a different UID/GID.
        self.run.chmod(0o700)
        try:
            with self.assertRaises(HoldPreparationBlocked):
                self.prepare()
            self.assertFalse(self.journal.exists())
            self.assertFalse(self.marker.exists())
        finally:
            self.run.chmod(0o755)

    def test_hold_write_collision_keeps_existing_evidence_and_pending_block(self):
        self.marker.write_text("protected marker")
        with self.assertRaises(HoldPreparationBlocked):
            self.prepare()
        self.assertEqual(self.marker.read_text(), "protected marker")
        self.assertTrue(self.journal.exists())
        # Invalid marker already blocks. After marker loss, pending still blocks.
        self.marker.unlink()
        self.assertTrue(self.observation()["active"])
        # Orphaned scope evidence must also retain a durable recovery block.
        # Use independent temporary subtests; never delete production evidence.
        for name in ("no-drain-release-binding.json",
                     "no-drain-agent-inventory.json"):
            with self.subTest(name=name):
                self.journal.unlink()  # disposable fixture reset only
                orphan = self.state / name
                orphan.write_bytes(b"prior evidence")
                orphan.chmod(0o600)
                with self.assertRaises(HoldPreparationBlocked):
                    self.prepare()
                self.assertEqual(orphan.read_bytes(), b"prior evidence")
                self.assertTrue(self.journal.exists())
                self.assertFalse(self.marker.exists())
                self.assertTrue(self.observation()["active"])
                orphan.unlink()


    def test_root_journal_and_privileged_exclusive_witness_is_local_and_negative(self):
        """Grouped read-only lease proof; EX refuses in-flight parent helper.

        Uses only a temporary durable journal, temporary /run marker and
        temporary flock witness. No real root, service, Agent or update.
        """
        import json
        from game_uptime_privileged_flock import (
            provision_privileged_helper_lock, shared_privileged_helper_lock,
        )
        from game_uptime_privileged_journal_witness import (
            PrivilegedJournalWitnessBlocked, local_privileged_journal_witness,
        )

        directory = self.run / "helper-locks"
        directory.mkdir(mode=0o755)
        inode = directory / "agent-privileged-operations.lock"
        provision_privileged_helper_lock(path=inode, trusted_uid=self.uid)
        self.prepare()

        def fence(**kwargs):
            values = {
                "expected_transaction_id": self.tx,
                "hold_path": self.marker,
                "journal_path": self.journal,
                "lock_path": inode,
                "trusted_uid": self.uid,
                "now": 1700000010,
            }
            values.update(kwargs)
            return local_privileged_journal_witness(**values)

        before_marker = self.marker.read_bytes()
        before_journal = self.journal.read_bytes()
        with fence() as evidence:
            self.assertEqual(evidence["transaction_id"], self.tx)
            self.assertTrue(evidence["journal_lease_matched_locally"])
            for key in (
                "all_helper_processes_opted_in_verified",
                "privileged_helper_acked", "controller_http_acked",
                "external_jobs_acked", "remote_agents_acked",
                "live_no_drain_authorized",
            ):
                self.assertIs(evidence[key], False)
            # A writer that arrived later must be refused while EX is held.
            from game_uptime_privileged_flock import PrivilegedHelperFenceUnavailable
            with self.assertRaises(PrivilegedHelperFenceUnavailable):
                with shared_privileged_helper_lock(
                    path=inode, trusted_uid=self.uid, enabled=True):
                    self.fail("EX cannot permit a new helper")

        self.assertEqual(self.marker.read_bytes(), before_marker)
        self.assertEqual(self.journal.read_bytes(), before_journal)

        # The same SH held by an already-admitted helper denies EX even if
        # the journal and hold are otherwise valid. No positive fallback.
        with shared_privileged_helper_lock(
                path=inode, trusted_uid=self.uid, enabled=True):
            with self.assertRaisesRegex(
                    PrivilegedJournalWitnessBlocked,
                    "privileged_helper_lock_not_exclusively_available"):
                with fence():
                    self.fail("local EX must not bypass an in-flight helper")

        for values in (
            {"expected_transaction_id": "f" * 32},
            {"now": 1700001000},   # lease expired
            {"expected_transaction_id": "bad"},
        ):
            with self.subTest(values=values):
                with self.assertRaises(PrivilegedJournalWitnessBlocked):
                    with fence(**values):
                        self.fail("mismatched transaction/lease cannot authorize")

        # A well-formed marker alone is not sufficient: durable pending
        # evidence must match byte-for-byte contract fields and ownership.
        original = self.journal.read_bytes()
        pending = json.loads(original)
        pending["transaction_id"] = "f" * 32
        self.journal.write_text(json.dumps(pending), encoding="utf-8")
        self.journal.chmod(0o600)
        try:
            with self.assertRaises(PrivilegedJournalWitnessBlocked):
                with fence():
                    self.fail("cross-transaction journal mismatch")
        finally:
            self.journal.write_bytes(original)
            self.journal.chmod(0o600)

        # An active observer must detect evidence modified *during* EX
        # before emitting a completed local observation.
        with self.assertRaisesRegex(
                PrivilegedJournalWitnessBlocked, "root_hold_pending_lease_mismatch"):
            with fence():
                pending = json.loads(original)
                pending["expires_at"] -= 1
                self.journal.write_text(json.dumps(pending), encoding="utf-8")
                self.journal.chmod(0o600)
        self.journal.write_bytes(original)
        self.journal.chmod(0o600)

        # The path must never be followed through a symlink to arbitrary
        # root-readable files, even if it contains a valid journal.
        destination = self.state / "protected-target.json"
        destination.write_bytes(original)
        destination.chmod(0o600)
        self.journal.unlink()
        self.journal.symlink_to(destination)
        try:
            with self.assertRaises(PrivilegedJournalWitnessBlocked):
                with fence():
                    self.fail("unsafe journal symlink")
            self.assertEqual(destination.read_bytes(), original)
        finally:
            self.journal.unlink()
            self.journal.write_bytes(original)
            self.journal.chmod(0o600)

        self.assertEqual(self.marker.read_bytes(), before_marker)
        with fence() as evidence:
            self.assertFalse(evidence["live_no_drain_authorized"])

        # Reuse the SAME durable transaction, now requiring EX on a second
        # inode held by detached Minecraft finalization children. Test the
        # combined witness once, without duplicating earlier lease tests.
        from game_uptime_finalization_flock import (
            FinalizationFenceUnavailable, provision_finalization_lock,
            shared_finalization_lock,
        )
        from game_uptime_privileged_journal_witness import (
            local_privileged_and_finalization_journal_witness,
        )

        # The standalone systemd package must enable both existing fences,
        # without weakening ProtectSystem or adding writable /run paths.
        services = ROOT / "agents/linux/services"
        identity = (services / "capivara-agent-runtime-identity.service").read_text()
        self.assertIn("game_uptime_privileged_flock.py --provision", identity)
        self.assertIn("game_uptime_finalization_flock.py --provision", identity)
        for name in ("runtime-identity", "materialize@", "firewall@",
                     "backup-create@", "backup-restore@"):
            unit = (services / ("capivara-agent-" + name + ".service")).read_text()
            self.assertIn("Environment=DSM928_AGENT_PRIVILEGED_FLOCK=1\n", unit)
            self.assertIn("game_uptime_privileged_flock.py --provision", unit)
            self.assertNotIn("ReadWritePaths=/run", unit)
        # Hybrid helpers run in independent systemd units, not in the
        # Worker process's environment. Each must opt in at its own boundary.
        for name in ("materialize@", "native-command@", "backup-restore@", "firewall@"):
            unit = (ROOT / "systemd" /
                    ("dsm-hybrid-agent-" + name + ".service.in")).read_text()
            self.assertIn("Environment=DSM928_AGENT_PRIVILEGED_FLOCK=1\n", unit)
            self.assertIn("@DSM_ROOT@/agents/linux/runtime/"
                          "game_uptime_privileged_flock.py --provision", unit)
            self.assertNotIn("ReadWritePaths=/run", unit)
            self.assertIn("NoNewPrivileges=true", unit)
        standalone = (services / "capivara-agent.service").read_text()
        self.assertIn("Environment=DSM928_AGENT_FINALIZATION_FLOCK=1\n", standalone)
        self.assertIn("Requires=capivara-agent-runtime-identity.service", standalone)
        final_dir = self.run / "finalization-locks"
        final_dir.mkdir(mode=0o755)
        child_inode = final_dir / "agent-finalization-operations.lock"
        agent_gid = os.getegid()
        provision_finalization_lock(
            path=child_inode, trusted_uid=self.uid, group_gid=agent_gid,
        )

        def both():
            return local_privileged_and_finalization_journal_witness(
                expected_transaction_id=self.tx,
                hold_path=self.marker, journal_path=self.journal,
                privileged_lock_path=inode, finalization_lock_path=child_inode,
                trusted_uid=self.uid, finalization_group_gid=agent_gid,
                now=1700000010,
            )

        before_journal = self.journal.read_bytes()
        with both() as witnessed:
            self.assertEqual(witnessed["transaction_id"], self.tx)
            self.assertEqual(witnessed["status"],
                             "root_journal_two_lock_families_observed_local_only")
            self.assertTrue(witnessed["finalization_child_lock_exclusive"])
            for key in (
                "all_finalization_children_opted_in_verified",
                "all_helper_processes_opted_in_verified", "external_jobs_acked",
                "remote_agents_acked", "live_no_drain_authorized",
            ):
                self.assertIs(witnessed[key], False)
            with self.assertRaises(FinalizationFenceUnavailable):
                with shared_finalization_lock(
                    path=child_inode, enabled=True,
                    trusted_uid=self.uid, group_gid=agent_gid,
                ):
                    self.fail("new child cannot bypass the combined EX")
        self.assertEqual(self.journal.read_bytes(), before_journal)
        self.assertEqual(self.marker.read_bytes(), before_marker)

        # The same inode also fences bounded Agent cycles/background work.
        # Reuse this fixture and assert that a held EX blocks admission;
        # an active hold remains blocking even after EX is released.
        from unittest.mock import patch
        from functools import partial
        import game_uptime_finalization_flock as runtime_fence
        import game_uptime_maintenance_hold as runtime_hold
        shared_fixture = partial(shared_finalization_lock, path=child_inode,
                                 enabled=True, trusted_uid=self.uid, group_gid=agent_gid)
        with patch.object(runtime_fence, "shared_finalization_lock", shared_fixture):
            with patch.object(runtime_hold, "observe", return_value={"active": False}):
                with runtime_fence.tracked_agent_operation() as admitted:
                    self.assertTrue(admitted)
                    with self.assertRaises(PrivilegedJournalWitnessBlocked):
                        with both():
                            self.fail("Agent operation bypassed EX")
                with both():
                    with runtime_fence.tracked_agent_operation() as admitted:
                        self.assertFalse(admitted)
            with patch.object(runtime_hold, "observe", return_value={"active": True}):
                with runtime_fence.tracked_agent_operation() as admitted:
                    self.assertFalse(admitted)

        # A child already inside SH prevents a false local completion.
        with shared_finalization_lock(
            path=child_inode, enabled=True,
            trusted_uid=self.uid, group_gid=agent_gid,
        ):
            with self.assertRaisesRegex(
                PrivilegedJournalWitnessBlocked,
                "finalization_child_lock_not_exclusively_available",
            ):
                with both():
                    self.fail("in-flight finalization must block coordinator")

        # The privileged helper family is independently required as well.
        with shared_privileged_helper_lock(
            path=inode, trusted_uid=self.uid, enabled=True,
        ):
            with self.assertRaisesRegex(
                PrivilegedJournalWitnessBlocked,
                "privileged_helper_lock_not_exclusively_available",
            ):
                with both():
                    self.fail("in-flight root helper must block coordinator")

        # Fail closed when the second inode is corrupt, without repair.
        child_inode.chmod(0o666)
        try:
            with self.assertRaisesRegex(
                PrivilegedJournalWitnessBlocked,
                "finalization_child_lock_not_exclusively_available",
            ):
                with both():
                    self.fail("unsafe finalization inode must not be accepted")
        finally:
            child_inode.chmod(0o660)

        # The observer must still reject a changed journal inside both EXs.
        with self.assertRaisesRegex(
            PrivilegedJournalWitnessBlocked, "root_hold_pending_lease_mismatch",
        ):
            with both():
                pending = json.loads(before_journal)
                pending["expires_at"] -= 1
                self.journal.write_text(json.dumps(pending), encoding="utf-8")
                self.journal.chmod(0o600)
        self.journal.write_bytes(before_journal)
        self.journal.chmod(0o600)


if __name__ == "__main__":
    unittest.main()
