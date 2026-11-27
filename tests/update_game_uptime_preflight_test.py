"""Read-only no-drain impact reporting for two real-shaped managed game units."""
import importlib.util
import hashlib
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = SourceFileLoader("game_uptime_preflight", str(ROOT/"update-manager/game-uptime-preflight.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class UpdatePreflightTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.installed = Path(tmp.name)/"installed"
        self.target = Path(tmp.name)/"target"
        self.installed.mkdir()
        self.target.mkdir()
        self.units = ["capivara-instance-minecraft-005.service", "capivara-instance-dayz-001.service"]

    def write(self, path, before, after):
        for root, value in ((self.installed,before),(self.target,after)):
            file = root/path
            file.parent.mkdir(parents=True,exist_ok=True)
            file.write_text(value)

    def inspect(self, unit):
        if "minecraft" in unit:
            raise module.reporter.guard.GateError(
                "game ExecStart points into replaceable DSM control-plane paths")
        return {"main_pid": 12345}

    def result(self):
        return module.preflight(self.installed,self.target,list_units=lambda: self.units,
                                inspect=self.inspect)

    def test_cosmetic_change_still_lists_exact_stop_and_restart_actions(self):
        self.write("dashboard/web/style.css", "old", "new")
        state = self.result()
        self.assertEqual(state["classification"],"review_only")
        self.assertFalse(state["live_no_drain_authorized"])
        self.assertTrue(state["current_updater_drains_active_games"])
        self.assertEqual([row["unit"] for row in state["planned_game_actions"]],sorted(self.units))
        self.assertTrue(all(row["action"] == "stop_and_restart" for row in
                            state["planned_game_actions"]))
        minecraft = next(x for x in state["units"] if "minecraft" in x["unit"])
        dayz = next(x for x in state["units"] if "dayz" in x["unit"])
        self.assertFalse(minecraft["no_drain_candidate"])
        self.assertTrue(dayz["no_drain_candidate"])
        self.assertFalse(dayz["no_drain_authorized"])

    def test_runtime_change_requires_maintenance_even_for_safe_unit(self):
        self.write("agents/linux/runtime/agent.py","old","new")
        state=self.result()
        self.assertEqual(state["classification"],"maintenance_required")
        self.assertTrue(state["requires_game_drain"])
        self.assertFalse(any(x["no_drain_candidate"] for x in state["units"]))
        self.write("update-manager/game-uptime-file-transaction.py", "old", "new")
        state = self.result()
        boundary = module._execution_boundary(state)
        self.assertEqual(boundary["release_path"],
                         "bootstrap_requires_separately_approved_maintenance")
        self.assertFalse(boundary["ordinary_draining_update_automatically_selected"])
        self.assertFalse(boundary["live_no_drain_authorized"])
        installed_owner = module._load("dsm928_installed_owner_test",
                                       "game-uptime-installed-transaction.py")
        with self.assertRaises(installed_owner.InstalledTransactionBlocked):
            installed_owner._validate_plan(state)
        with self.assertRaises(installed_owner.InstalledTransactionBlocked):
            installed_owner.run(self.target)
        self.assertIn("retained_installed_admission_required", boundary["blockers"])
        self.assertIn("initial_fence_aware_installation_or_bootstrap_update_required",
                      boundary["static_blockers"])
        self.assertIn("operational_guarantees_unverified", boundary["operational_blockers"])
        # A signed compatible plan is not an operational admission.
        static = {"operational_release_review": {
                    "artifact_origin_verified": True, "target_tree_bound_to_signed_tar": True,
                    "verified_archive_sha256": "b"*64},
                  "release_impact": {"fixed_file_transaction_plan": {
                    "status": "compatible_file_plan_only",
                    "bootstrap_installation_required": False, "blockers": [],
                    "changed_paths": ["dashboard/web/style.css", "version"], "file_count": 2}}}
        self.assertEqual(installed_owner._validate_static_plan(static)[0], "b"*64)
        with self.assertRaises(installed_owner.InstalledTransactionBlocked):
            installed_owner._validate_plan(static)
        self.write("version", "2.0.133-rc.6", "2.0.133-rc.2")
        with self.assertRaises(installed_owner.InstalledTransactionBlocked):
            installed_owner._require_forward_version(self.installed, self.target)
        self.write("version", "2.0.133-rc.6", "2.0.133-rc.7")
        installed_owner._require_forward_version(self.installed, self.target)
        self.write("version", "2.0.133-rc.6", "2.0.133-rc.6+rebuild")
        with self.assertRaises(installed_owner.InstalledTransactionBlocked):
            installed_owner._require_forward_version(self.installed, self.target)
        # Recovery must preserve the original lease, package and complete
        # inventory; it must not retry a fresh transaction after a crash.
        tx = "a"*32
        now = 1700000100
        recovery = {"kind": "DSM928InstalledUptimeTransaction", "schema_version": 2,
                    "scope": {"transaction_id": tx, "release_sha256": "b"*64,
                              "issued_at": 1700000000, "expires_at": 1700000900,
                              "expected_agent_ids": ["hybrid", "vps"]},
                    "local_hybrid_agent_id": "hybrid", "product_file_journal_sha256": "c"*64,
                    "product_identity": [1000, 1000], "live_no_drain_authorized": False,
                    "status": "prepared"}
        options = installed_owner._validate_recovery_report(recovery, tx, now)
        self.assertTrue(options["recover_existing"])
        self.assertEqual(options["expires_at"], 1700000900)
        for bad in ({**recovery, "status": "manual_recovery_required"},
                    {**recovery, "scope": {**recovery["scope"], "expires_at": now}},
                    {**recovery, "scope": {**recovery["scope"], "expected_agent_ids": ["vps"]}},
                    {**recovery, "schema_version": 1},
                    {**recovery, "live_no_drain_authorized": True}):
            with self.assertRaises(installed_owner.InstalledTransactionBlocked):
                installed_owner._validate_recovery_report(bad, tx, now)
        with self.assertRaises(installed_owner.InstalledTransactionBlocked):
            installed_owner.recover(tx)

    def test_installed_restart_selection_and_terminal_receipts_stay_guarded(self):
        from unittest.mock import Mock
        owner = module._load("dsm928_installed_restart_contract_test",
                             "game-uptime-installed-transaction.py")
        self.write("dashboard/workers/worker.py", "x = 1", "x = 2")
        self.write("version", "2.0.133-rc.6", "2.0.133-rc.7")
        impact = module.plan.analyze(self.installed, self.target)
        report = {"release_impact": impact, "operational_release_review": {
            "artifact_origin_verified": True, "target_tree_bound_to_signed_tar": True,
            "verified_archive_sha256": "b"*64}}
        digest, paths, restart = owner._select_candidate(report)
        self.assertEqual(digest, "b"*64)
        self.assertEqual(set(paths), {"dashboard/workers/worker.py", "version"})
        self.assertTrue(restart)
        with self.assertRaisesRegex(owner.InstalledTransactionBlocked,
                                    "preparation_evidence_unavailable"):
            owner._validate_plan(report)
        bad = {**impact, "fixed_file_transaction_plan": {
            **impact["fixed_file_transaction_plan"], "bootstrap_installation_required": True}}
        with self.assertRaises(owner.InstalledTransactionBlocked):
            owner._select_candidate({**report, "release_impact": bad})

        # Pure orchestration fixture: no installed admission, systemd, or game
        # operation is exercised by these mocked callbacks.
        engine = Mock()
        scope = {"all_mutators_fenced": False, "external_jobs_acked": False,
                 "checkpoint": Mock()}
        with self.assertRaises(owner.InstalledTransactionBlocked):
            owner._execute_file_transaction(engine, scope, restart_required=True)
        engine.apply.assert_not_called()
        count = [0]
        def restart_once():
            count[0] += 1
            return {"status": "restart_transition_recorded", "sequence": count[0],
                    "live_no_drain_authorized": False}
        scope.update(all_mutators_fenced=True, external_jobs_acked=True,
                     restart_receipt_count=lambda: count[0],
                     restart_control_plane=restart_once)
        self.assertEqual(owner._execute_file_transaction(engine, scope, restart_required=True),
                         "verified")
        self.assertEqual(count[0], 1)
        engine.rollback.assert_not_called()
        with self.assertRaises(owner.InstalledTransactionBlocked):
            owner._verify_terminal_restart(scope, False, "verified")
        count[0] = 0
        engine.reset_mock()
        engine.verify_terminal.side_effect = [None, RuntimeError("failed verification"), None]
        self.assertEqual(owner._execute_file_transaction(engine, scope, restart_required=True),
                         "rolled_back")
        self.assertEqual(count[0], 2)
        engine.rollback.assert_called_once()
        with self.assertRaises(owner.InstalledTransactionBlocked):
            owner._verify_terminal_restart(scope, True, "verified")

    def test_bootstrap_stages_both_snapshots_without_publishing(self):
        import json
        bootstrap = module._load("dsm928_bootstrap_stage_test",
                                 "game-uptime-bootstrap-stage.py")
        reviewed = self.target
        payload = reviewed / "payload"
        for name in ("update-manager", "agents/linux/runtime", "dashboard", "systemd"):
            (payload / name).mkdir(parents=True)
        (payload / "version").write_text("2.0.133-rc.9\n")
        (reviewed / "reviewed-commit").write_text("a"*40 + "\n")
        for suffix in (".tar.gz", ".manifest.json", ".provenance.json", ".provenance.sig"):
            (reviewed / ("capivara-dsm-2.0.133-rc.9" + suffix)).write_text("fixture")
        for name in bootstrap.MODULES:
            (payload / "agents/linux/runtime" / name).write_text("# " + name)
        (payload / "agents/linux/runtime/console_supervisor.py").write_text("# fixture")
        stage = self.installed / "stage"
        stage.mkdir(mode=0o700)
        result = bootstrap._stage_bundle(reviewed, stage, version="2.0.133-rc.9",
                                         commit="a"*40, digest="b"*64)
        self.assertFalse(result["published"])
        self.assertFalse(result["live_no_drain_authorized"])
        for name in bootstrap.MODULES:
            self.assertEqual((stage / "agent" / name).read_bytes(),
                (stage / "updater/agents/linux/runtime" / name).read_bytes())
        self.assertEqual(json.loads((stage / "supervisor-versions/active-pin.json").read_text()),
                         {"sha256": result["supervisor_sha256"]})
        self.assertEqual((stage / "installed-baseline/payload/version").read_text(),
                         "2.0.133-rc.9\n")
        self.assertFalse((stage / "installed-baseline/local-overrides.json").exists())

    def test_changed_source_cache_is_never_removed_by_transaction(self):
        from pathlib import Path
        engine = module._load("dsm928_cache_guard_test",
                              "game-uptime-file-transaction.py")
        self.write("dashboard/probe.py", "x=1", "x=2")
        source = self.installed / "dashboard/probe.py"
        engine._require_no_source_cache(source)
        cache = source.parent / "__pycache__"
        cache.mkdir()
        entry = cache / "probe.cpython-312.pyc"
        entry.write_bytes(b"unsafe or obsolete")
        with self.assertRaisesRegex(engine.FileTransactionBlocked, "python_cache"):
            engine._require_no_source_cache(source)
        self.assertEqual(entry.read_bytes(), b"unsafe or obsolete")
        entry.unlink()
        cache.rmdir()
        cache.symlink_to(source.parent)
        with self.assertRaisesRegex(engine.FileTransactionBlocked, "cache_directory"):
            engine._require_no_source_cache(source)

    def test_preparation_and_retained_admission_are_distinct(self):
        # Pure validator fixture: a preparation report is not an installed
        # permission, even when the eligibility inputs are complete.
        owner = module._load("dsm928_preparation_boundary_test",
                             "game-uptime-installed-transaction.py")
        from unittest.mock import Mock
        self.write("dashboard/web/style.css", "old", "new")
        report = {
            "release_impact": module.plan.analyze(self.installed, self.target),
            "operational_execution_boundary": {"static_blockers": [],
                                               "blockers": ["operational_guarantees_unverified"]},
            "operational_release_review": {
                "artifact_origin_verified": True, "target_tree_bound_to_signed_tar": True,
                "verified_archive_sha256": "b"*64,
                "maintenance_hold": {"active": False},
                "operational_preparation_blockers": [],
                "operational_guarantees_complete": False,
                "operational_quiescence_acked": False,
                "external_jobs_acked": False,
                "durable_cross_host_recovery_verified": False,
            },
            "no_drain_handoff_witness_verified": True,
            "no_drain_operational_coverage_verified": True,
            "no_drain_compatibility_verified": True,
        }
        self.assertEqual(owner._validate_plan(report),
                         ("b"*64, ["dashboard/web/style.css"], False))
        bad = {**report, "operational_release_review": {
            **report["operational_release_review"],
            "operational_preparation_blockers": ["external_jobs_quiescence_not_integrated"]}}
        with self.assertRaisesRegex(owner.InstalledTransactionBlocked,
                                    "external_jobs_quiescence_not_integrated"):
            owner._validate_plan(bad)
        with self.assertRaises(owner.InstalledTransactionBlocked):
            owner._validate_plan({**report, "no_drain_compatibility_verified": False})
        options = {"transaction_id": "a"*32, "release_sha256": "b"*64,
                   "issued_at": 1700000000, "expires_at": 1700000900,
                   "expected_agent_ids": ["hybrid", "vps"], "local_hybrid_agent_id": "hybrid"}
        checkpoint = Mock()
        scope = {"kind": "DSM928InstalledHostScope",
                 **{key: options[key] for key in ("transaction_id", "release_sha256",
                                                   "issued_at", "expires_at", "local_hybrid_agent_id")},
                 "agent_ids": ["hybrid", "vps"],
                 "controller_registry_inventory_matched": True,
                 "known_database_job_queues_terminal": True,
                 "all_mutators_fenced": False, "external_jobs_acked": False,
                 "checkpoint": checkpoint, "finalize_terminal": Mock()}
        with self.assertRaisesRegex(owner.InstalledTransactionBlocked,
                                    "retained_operational_guarantees_missing"):
            owner._require_retained_admission(scope, options)
        with self.assertRaisesRegex(owner.InstalledTransactionBlocked,
                                    "retained_scope_binding_mismatch"):
            owner._require_retained_admission({**scope, "expires_at": 1700001000}, options)
        checkpoint.assert_not_called()
        retained = {
            **scope, "all_mutators_fenced": True, "external_jobs_acked": True,
        }
        with self.assertRaisesRegex(owner.InstalledTransactionBlocked,
                                    "managed_local_mutator_coverage_unverified"):
            owner._require_retained_admission(retained, options)
        observer = Mock(return_value=())
        owner._require_retained_admission({
            **retained, "managed_mutator_blockers": observer,
        }, options)
        observer.assert_called_once_with()

    def test_local_scope_refuses_to_activate_unfenced_topology_writer(self):
        from unittest.mock import Mock, patch

        lease = module._load("dsm928_host_topology_test", "game-uptime-local-scope-lease.py")
        settled = ("LoadState=loaded\nActiveState=active\nSubState=exited\n"
                   "RemainAfterExit=yes\nNeedDaemonReload=no\n")
        with patch.object(lease.subprocess, "run", return_value=Mock(stdout=settled)):
            lease._check_controller_topology_settled()
        for observation in (
                settled.replace("SubState=exited", "SubState=running"),
                settled.replace("ActiveState=active", "ActiveState=inactive"),
                settled.replace("NeedDaemonReload=no", "NeedDaemonReload=yes")):
            with patch.object(lease.subprocess, "run", return_value=Mock(stdout=observation)):
                with self.assertRaisesRegex(lease.LocalScopeLeaseBlocked,
                                            "unfenced_controller_topology_activation"):
                    lease._check_controller_topology_settled()

    def test_hybrid_mutator_inventory_verifies_sources_and_effective_units(self):
        from unittest.mock import Mock, patch

        lease = module._load("dsm928_hybrid_inventory_test", "game-uptime-local-scope-lease.py")
        snapshot, units = self.target, self.installed / "units"
        installed = self.installed
        units.mkdir()
        for name in lease._PINNED_MUTATORS:
            self.write(name, "audited source", "audited source")
        helper_names = {f"dsm-hybrid-agent-{kind}@.service" for kind in lease._HYBRID_HELPERS}
        topology = "dsm-controller-service-topology.service"
        for unit in helper_names | {topology}:
            (snapshot / "systemd").mkdir(exist_ok=True)
            expected = snapshot / "systemd" / (unit + ".in" if unit in helper_names else unit)
            expected.write_text("[Service]\nType=oneshot\n")
            (units / unit).write_bytes(expected.read_bytes())

        observations = {name: {"start_ticks": 10**16, "pid": 123} for name in lease.WORKERS}
        identity = Mock()
        identity._systemd_status.return_value = {"User": "dsm"}
        identity._workers_identity.return_value = {
            "all_nine_workers_verified": True, "worker_identities": observations,
        }
        extra = ""
        dropin = ""

        def systemctl(*args):
            if args[0] == "list-unit-files":
                return "".join(f"{unit} static\n" for unit in sorted(helper_names)) + extra
            unit = args[1].replace("@dsm928-probe.", "@.")
            return (f"LoadState=loaded\nFragmentPath={units / unit}\nDropInPaths={dropin}\n"
                    "NeedDaemonReload=no\nKillMode=control-group\n")

        read = lease._mutator_bytes
        with patch.object(lease, "_mutator_bytes", side_effect=lambda path, **_: read(path)), \
                patch.object(lease, "_check_hybrid_helper_selectors"):
            lease._check_hybrid_mutators(installed, snapshot, units,
                                         systemctl=systemctl, identity=identity)
            extra = "dsm-hybrid-agent-unknown@.service static\n"
            with self.assertRaisesRegex(lease.LocalScopeLeaseBlocked, "uncovered_installed"):
                lease._check_hybrid_mutators(installed, snapshot, units,
                                             systemctl=systemctl, identity=identity)
            extra = ""
            dropin = "/etc/systemd/system/override.conf"
            with self.assertRaisesRegex(lease.LocalScopeLeaseBlocked, "unit_unverified"):
                lease._check_hybrid_mutators(installed, snapshot, units,
                                             systemctl=systemctl, identity=identity)
            dropin = ""
            (installed / lease._PINNED_MUTATORS[0]).write_text("unreviewed launcher")
            with self.assertRaisesRegex(lease.LocalScopeLeaseBlocked, "source_changed"):
                lease._check_hybrid_mutators(installed, snapshot, units,
                                             systemctl=systemctl, identity=identity)

    def test_root_reviewed_inputs_bind_inventory_and_contracts_to_archive(self):
        import hashlib
        import json
        import os

        if os.geteuid() != 0:
            self.skipTest("requires disposable root ownership")
        reviewer = module._load("dsm928_operational_inputs_test",
                                "game-uptime-operational-release-review.py")
        self.write("version", "2.0.998", "2.0.999")
        folder = self.target / "reviewed-release"
        folder.mkdir()
        (self.target / "supervisor-versions").mkdir()
        contract = {field: "v1" for field in module.compatibility.CONTRACT_FIELDS}
        source = "WIRE_CONTRACT = " + repr(contract) + "\n"
        for relative in ("dashboard/game_uptime_heartbeat_compat.py",
                         "agents/linux/runtime/game_uptime_agent_wire.py"):
            self.write(relative, source, source)
        record = {
            "schema_version": 1, "release_sha256": "b" * 64,
            "installed_version": "2.0.998",
            "controller_contract": contract, "agent_contract": contract,
            "expected_active_units": self.units,
            "supervisor_expected_sha256": "c" * 64,
        }
        path = folder / "operational-inputs.json"
        raw = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        path.write_bytes(raw)
        proof = {"artifact_origin_verified": True,
                 "target_tree_bound_to_signed_tar": True,
                 "verified_archive_sha256": record["release_sha256"]}
        inputs, digest = reviewer.read_operational_inputs(
            self.installed, self.target, proof, review_dir=folder)
        self.assertEqual(inputs["expected_active_units"], self.units)
        self.assertEqual(inputs["controller_contract"], contract)
        self.assertEqual(inputs["agent_contract"], contract)
        self.assertEqual(digest, hashlib.sha256(raw).hexdigest())
        with self.assertRaisesRegex(reviewer.OperationalReviewBlocked, "binding_invalid"):
            reviewer.read_operational_inputs(self.installed, self.target, {
                **proof, "verified_archive_sha256": "d" * 64,
            }, review_dir=folder)
        controller = self.target / "dashboard/game_uptime_heartbeat_compat.py"
        controller.write_text("WIRE_CONTRACT = {'protocol': 'unreviewed'}\n")
        with self.assertRaisesRegex(reviewer.OperationalReviewBlocked, "wire_contract_mismatch"):
            reviewer.read_operational_inputs(self.installed, self.target, proof, review_dir=folder)
        path.chmod(0o666)
        with self.assertRaisesRegex(reviewer.OperationalReviewBlocked, "untrusted"):
            reviewer.read_operational_inputs(self.installed, self.target, proof, review_dir=folder)

    def test_bad_inventory_fails_closed(self):
        self.write("dashboard/web/style.css","old","new")
        state=module.preflight(self.installed,self.target,list_units=lambda:["invalid.service"])
        self.assertEqual(state["classification"],"blocked")
        self.assertTrue(state["requires_game_drain"])
        self.assertFalse(state["live_no_drain_authorized"])
        self.assertEqual(state["planned_game_actions"],[])

    def test_symlink_fails_closed(self):
        (self.target/"escape").symlink_to(self.installed)
        state=self.result()
        self.assertEqual(state["classification"],"blocked")
        self.assertTrue(state["requires_game_drain"])

    def test_zero_active_units_still_never_authorizes_no_drain(self):
        self.write("dashboard/web/style.css","old","new")
        state=module.preflight(self.installed,self.target,list_units=lambda: [],
                               inspect=self.inspect)
        self.assertEqual(state["classification"],"review_only")
        self.assertFalse(state["live_no_drain_authorized"])
        self.assertEqual(state["units"],[])


    def test_preflight_embeds_fail_closed_compatibility_gate(self):
        self.write("dashboard/web/style.css", "old", "new")
        state = self.result()
        self.assertFalse(state["no_drain_compatibility_verified"])
        self.assertIn("controller_agent_contract_missing", state["compatibility_gate"]["blockers"])
        self.assertFalse(any(row["no_drain_compatibility_verified"] for row in state["units"]))
        self.assertFalse(state["live_no_drain_authorized"])

    def test_matching_contract_requires_verified_systemd_pin_not_boolean(self):
        self.write("dashboard/web/style.css", "old", "new")
        for root in (self.installed, self.target):
            supervisor = root / module.compatibility.SUPERVISOR_RELATIVE
            supervisor.parent.mkdir(parents=True, exist_ok=True)
            supervisor.write_text("same supervisor")
        contract = {"protocol": "v1", "schema": "22",
                    "controller_api": "v2", "agent_api": "v2"}
        versions = self.installed.parent / "versions"
        versions.mkdir()
        digest = hashlib.sha256(b"pinned fixture").hexdigest()
        pinned = versions / ("console-supervisor-" + digest + ".py")
        pinned.write_bytes(b"pinned fixture")
        pinned.chmod(0o444)
        def observed(unit):
            if "minecraft" not in unit:
                return {"main_pid": 12345, "start_stamp": 666}
            return {"main_pid": 54321, "start_stamp": 777,
                    "exec": "path=/usr/bin/python3 ; argv[]=/usr/bin/python3 " +
                            str(pinned) + " --socket /tmp/fixture.sock -- /usr/bin/sleep 15 ;",
                    "fragment": "/etc/systemd/system/" + unit}
        kwargs = dict(list_units=lambda: self.units, inspect=observed,
                      controller_contract=contract, agent_contract=contract)
        blocked = module.preflight(self.installed, self.target, **kwargs,
                                   supervisor_pinned=True)
        self.assertFalse(blocked["no_drain_compatibility_verified"])
        self.assertIn("pinned_supervisor_evidence_missing",
                      blocked["supervisor_pin_evidence"]["blockers"])
        candidate = module.preflight(
            self.installed, self.target, **kwargs,
            supervisor_versions_dir=versions, supervisor_expected_sha256=digest)
        self.assertTrue(candidate["supervisor_pin_evidence"]["verified"])
        self.assertTrue(candidate["no_drain_compatibility_verified"])
        self.assertFalse(candidate["live_no_drain_authorized"])
        self.assertTrue(candidate["current_updater_drains_active_games"])

    def test_pid_change_between_inventory_and_supervisor_inspection_blocks(self):
        self.write("dashboard/web/style.css", "old", "new")
        versions = self.installed.parent / "versions"
        versions.mkdir()
        digest = hashlib.sha256(b"supervisor").hexdigest()
        path = versions / ("console-supervisor-" + digest + ".py")
        path.write_bytes(b"supervisor")
        path.chmod(0o444)
        for root in (self.installed, self.target):
            source = root / module.compatibility.SUPERVISOR_RELATIVE
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("supervisor")
        calls = {"minecraft": 0}
        def observed(unit):
            if "minecraft" not in unit:
                return {"main_pid": 12345, "start_stamp": 666}
            calls["minecraft"] += 1
            return {"main_pid": 532 if calls["minecraft"] == 1 else 533,
                    "start_stamp": 777,
                    "exec": "path=/usr/bin/python3 ; argv[]=/usr/bin/python3 " +
                            str(path) + " --socket /tmp/test.sock -- /usr/bin/sleep 15 ;",
                    "fragment": "/etc/systemd/system/" + unit}
        contract = {"protocol": "v1", "schema": "22",
                    "controller_api": "v2", "agent_api": "v2"}
        result = module.preflight(
            self.installed, self.target, list_units=lambda: self.units, inspect=observed,
            controller_contract=contract, agent_contract=contract,
            supervisor_versions_dir=versions, supervisor_expected_sha256=digest)
        self.assertFalse(result["supervisor_pin_evidence"]["verified"])
        self.assertTrue(any("process identity changed" in blocker
                            for blocker in result["supervisor_pin_evidence"]["blockers"]))
        self.assertFalse(result["no_drain_compatibility_verified"])
        self.assertFalse(result["live_no_drain_authorized"])


    def test_operational_coverage_never_accepts_stopped_minecraft(self):
        self.write("dashboard/web/style.css", "old", "new")
        actual = [unit for unit in self.units if "dayz" in unit]
        result = module.preflight(
            self.installed, self.target,
            list_units=lambda: actual,
            inspect=lambda unit: {"main_pid": 3456, "start_stamp": 7890},
            expected_active_units=self.units,
        )
        self.assertFalse(result["no_drain_operational_coverage_verified"])
        self.assertEqual(
            result["operational_coverage"]["missing_active_units"],
            [next(unit for unit in self.units if "minecraft" in unit)],
        )
        self.assertFalse(result["live_no_drain_authorized"])

    def test_operational_coverage_requires_explicit_full_active_baseline(self):
        self.write("dashboard/web/style.css", "old", "new")
        inspect = lambda unit: {"main_pid": 3456 if "dayz" in unit else 4567,
                                "start_stamp": 7890 if "dayz" in unit else 8901}
        unknown = module.preflight(
            self.installed, self.target, list_units=lambda: self.units,
            inspect=inspect,
        )
        self.assertFalse(unknown["no_drain_operational_coverage_verified"])
        confirmed = module.preflight(
            self.installed, self.target, list_units=lambda: self.units,
            inspect=inspect, expected_active_units=self.units,
        )
        self.assertTrue(confirmed["no_drain_operational_coverage_verified"])
        self.assertFalse(confirmed["live_no_drain_authorized"])
        self.assertTrue(confirmed["current_updater_drains_active_games"])


    def test_operational_coverage_accepts_exact_host_local_inventory(self):
        self.write("dashboard/web/style.css", "old", "new")
        for units in ([u for u in self.units if "minecraft" in u],
                      [u for u in self.units if "dayz" in u], []):
            with self.subTest(units=units):
                result = module.preflight(
                    self.installed, self.target, list_units=lambda: units,
                    inspect=lambda unit: {"main_pid": 3456, "start_stamp": 7890},
                    expected_active_units=units,
                )
                self.assertTrue(result["no_drain_operational_coverage_verified"])
                self.assertFalse(result["live_no_drain_authorized"])
        # A remote game is not a substitute for a missing declared local unit.
        missing = module.preflight(
            self.installed, self.target, list_units=lambda: [],
            inspect=lambda unit: {"main_pid": 3456, "start_stamp": 7890},
            expected_active_units=[self.units[0]],
        )
        self.assertFalse(missing["no_drain_operational_coverage_verified"])
        self.assertEqual(missing["operational_coverage"]["missing_active_units"],
                         [self.units[0]])

    def test_full_systemd_pid_and_unit_digest_witness_passes_two_points(self):
        self.write("dashboard/web/style.css", "old", "new")
        digest = "a" * 64
        calls = []
        def inspect(unit):
            calls.append(unit)
            return {"main_pid": 1234 if "dayz" in unit else 5678,
                    "start_stamp": 222 if "dayz" in unit else 333,
                    "unit_config_sha256": digest}
        result = module.preflight(
            self.installed, self.target,
            list_units=lambda: self.units, inspect=inspect,
            expected_active_units=self.units)
        self.assertTrue(result["handoff_witness"]["verified_for_disposable_rehearsal"])
        self.assertEqual(result["handoff_witness"]["active_units_witnessed"], 2)
        self.assertEqual(len(calls), 4, "inspect once during inventory and again at handoff")
        self.assertFalse(result["no_drain_disposable_rehearsal_candidate"],
                         "missing authenticated contracts and supervisor evidence")
        self.assertFalse(result["live_no_drain_authorized"])

    def test_pid_change_at_handoff_blocks_even_when_initial_sample_verified(self):
        self.write("dashboard/web/style.css", "old", "new")
        calls = {}
        def inspect(unit):
            calls[unit] = calls.get(unit, 0) + 1
            return {"main_pid": (99999 if calls[unit] > 1 and "dayz" in unit
                                 else 12345),
                    "start_stamp": 444,
                    "unit_config_sha256": "b" * 64}
        result = module.preflight(
            self.installed, self.target,
            list_units=lambda: self.units, inspect=inspect,
            expected_active_units=self.units)
        self.assertFalse(result["no_drain_handoff_witness_verified"])
        self.assertIn("active_game_pid_or_unit_witness_changed",
                      result["handoff_witness"]["blockers"])
        self.assertFalse(result["no_drain_disposable_rehearsal_candidate"])
        self.assertFalse(result["live_no_drain_authorized"])

    def test_new_game_started_between_inventory_and_handoff_blocks(self):
        self.write("dashboard/web/style.css", "old", "new")
        calls = [0]
        def list_units():
            calls[0] += 1
            return self.units if calls[0] == 1 else self.units + [
                "capivara-instance-dayz-999.service"]
        result = module.preflight(
            self.installed, self.target, list_units=list_units,
            inspect=lambda unit: {"main_pid": 12345, "start_stamp": 555,
                                  "unit_config_sha256": "c" * 64},
            expected_active_units=self.units)
        self.assertFalse(result["no_drain_handoff_witness_verified"])
        self.assertIn("active_game_unit_set_changed", result["handoff_witness"]["blockers"])
        self.assertFalse(result["live_no_drain_authorized"])

    def test_missing_full_unit_digest_cannot_qualify_as_pid_witness(self):
        self.write("dashboard/web/style.css", "old", "new")
        result = module.preflight(
            self.installed, self.target,
            list_units=lambda: self.units,
            inspect=lambda unit: {"main_pid": 12345, "start_stamp": 555},
            expected_active_units=self.units)
        self.assertFalse(result["no_drain_handoff_witness_verified"])
        self.assertIn("initial_game_unit_witness_missing",
                      result["handoff_witness"]["blockers"])


    def test_handoff_exposes_only_normalized_process_witnesses(self):
        self.write("dashboard/web/style.css", "old", "new")
        result = module.preflight(
            self.installed, self.target,
            list_units=lambda: self.units,
            inspect=lambda unit: {"main_pid": 111 if "dayz" in unit else 222,
                                  "start_stamp": 888, "unit_config_sha256": "a" * 64},
            expected_active_units=self.units)
        witness = result["handoff_witness"]
        self.assertTrue(witness["verified_for_disposable_rehearsal"])
        self.assertEqual(len(witness["original_units"]), 2)
        self.assertEqual(set(witness["original_units"][0]), {
            "unit", "pid", "started", "state", "unit_config_sha256"})
        self.assertFalse(result["live_no_drain_authorized"])



    def test_advisory_change_tier_never_changes_actual_stop_actions(self):
        self.write("dashboard/workers/worker.py", "old", "new")
        result = self.result()
        self.assertEqual(result["proposed_no_drain_change_tier"],
                         "control_plane_restart_candidate")
        self.assertFalse(result["proposed_no_drain_live_authorized"])
        self.assertTrue(result["current_updater_drains_active_games"])
        self.assertTrue(all(x["action"] == "stop_and_restart"
                            for x in result["planned_game_actions"]))
        self.assertFalse(result["no_drain_disposable_rehearsal_candidate"])

        # Installed caches and umask-induced mode drift must be visible
        # separately from real content changes, without weakening admission.
        self.write("dashboard/web/mode-only.css", "same", "same")
        (self.installed / "dashboard/web/mode-only.css").chmod(0o644)
        (self.target / "dashboard/web/mode-only.css").chmod(0o600)
        cache = self.installed / "dashboard/__pycache__/worker.cpython-312.pyc"
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(b"generated-cache")
        report = module.plan.analyze(self.installed, self.target)
        counts = report["difference_counts"]
        self.assertGreaterEqual(counts["mode_only"], 1)
        self.assertGreaterEqual(counts["content_changed"], 1)
        self.assertGreaterEqual(counts["removed"], 1)
        self.assertEqual(counts["python_cache_paths"], 1)
        self.assertEqual(sum(counts[k] for k in ("added", "removed", "content_changed", "mode_only")),
                         report["changed_count"])
        self.assertTrue(report["requires_game_drain"])
        self.assertFalse(report["live_no_drain_authorized"])


    def test_operator_signed_release_review_is_read_only_and_never_authorizes(self):
        """The actual no-drain-report entrypoint must expose missing live proof."""
        import io
        import json
        import sys
        from contextlib import redirect_stdout
        from unittest.mock import patch

        review = module._load(
            "dsm928_operational_review_direct",
            "game-uptime-operational-release-review.py",
        )
        # An untrusted key/review directory can never replace the fixed
        # root-controlled production source, even if the directory exists.
        spoofed = self.installed.parent / "operator-signature"
        spoofed.mkdir()
        forged = review.evaluate(self.target, review_dir=spoofed)
        self.assertFalse(forged["artifact_origin_verified"])
        self.assertFalse(forged["target_tree_bound_to_signed_tar"])
        self.assertFalse(forged["live_no_drain_authorized"])
        self.assertTrue(any("production_trust_path_is_fixed" in b
                            for b in forged["blockers"]))

        fake_preflight = {
            "kind": "CapivaraDSMNoDrainPreflight",
            "classification": "review_only",
            "current_updater_drains_active_games": True,
            "live_no_drain_authorized": False,
        }
        output = io.StringIO()
        with (patch.object(module, "preflight", return_value=fake_preflight),
              patch.object(sys, "argv", [
                  "game-uptime-preflight.py", str(self.installed), str(self.target),
              ]),
              redirect_stdout(output)):
            returncode = module.main()
        self.assertEqual(returncode, 0, "read-only report retains legacy exit behavior")
        evidence = json.loads(output.getvalue())
        verified = evidence["operational_release_review"]
        self.assertFalse(verified["artifact_origin_verified"])
        self.assertFalse(verified["operational_quiescence_acked"])
        self.assertFalse(verified["external_jobs_acked"])
        self.assertFalse(verified["durable_cross_host_recovery_verified"])
        self.assertFalse(verified["live_no_drain_authorized"])
        # Real local lock inodes are inspected, rather than accepting
        # self-declared "idle" booleans or synthetic remote ACKs.
        local_fences = verified["local_kernel_fences"]
        self.assertEqual(local_fences["status"],
                         "incomplete_live_admission_evidence")
        self.assertEqual(local_fences["observed_worker_count"], 9)
        self.assertEqual(len(local_fences["workers"]), 9)
        self.assertFalse(local_fences["controller_http_acked"])
        self.assertFalse(local_fences["workers_acked"])
        self.assertFalse(local_fences["external_jobs_acked"])
        self.assertFalse(local_fences["remote_agents_acked"])
        self.assertFalse(local_fences["live_no_drain_authorized"])
        identity = verified["daemon_process_identity"]
        self.assertEqual(identity["status"], "read_only_partial_daemon_identity")
        self.assertFalse(identity["controller_mutations_acked"])
        self.assertFalse(identity["worker_cycles_acked"])
        self.assertFalse(identity["remote_agents_acked"])
        self.assertFalse(identity["external_jobs_acked"])
        self.assertFalse(identity["live_no_drain_authorized"])
        self.assertIn("updater_no_drain_production_entrypoint_not_authorized",
                      verified["blockers"])
        self.assertTrue(evidence["current_updater_drains_active_games"])


    def test_controller_daemon_identity_requires_stable_pid_and_flock_optin(self):
        """Pure identity contract; no real systemd mutation or mock ACKs."""
        from unittest.mock import patch
        probe = module._load(
            "dsm928_daemon_identity_strict_contract",
            "game-uptime-live-daemon-identity.py",
        )
        unit = {
            "ActiveState": "active", "SubState": "running",
            "MainPID": "4821", "User": "capivara",
            "ControlGroup": "/system.slice/dsm-dashboard.service",
        }
        process = {
            "pid": 4821, "start_ticks": 1777, "uid": 1001,
            "argv": ("python3", "/opt/dsm/dashboard/server_part22.py"),
            "cgroup": unit["ControlGroup"], "flock_opted_in": True,
        }
        self.assertTrue(probe.verify_controller_snapshot(
            unit, dict(unit), process, dict(process), expected_uid=1001))
        self.assertFalse(probe.verify_controller_snapshot(
            unit, unit, {**process, "flock_opted_in": False},
            {**process, "flock_opted_in": False}, expected_uid=1001))
        for altered in (
            {**process, "pid": 4822},
            {**process, "start_ticks": 0},
            {**process, "uid": 0},
            {**process, "argv": ("python3", "/tmp/server_part22.py")},
            {**process, "cgroup": "/system.slice/other.service"},
        ):
            with self.subTest(mutation=altered):
                with self.assertRaises(ValueError):
                    probe.verify_controller_snapshot(
                        unit, unit, altered, altered, expected_uid=1001)
        with self.assertRaises(ValueError):
            probe.verify_controller_snapshot(
                unit, unit, process, {**process, "start_ticks": 1778},
                expected_uid=1001)
        with self.assertRaises(ValueError):
            probe.verify_controller_snapshot(
                unit, {**unit, "MainPID": "4822"}, process, process,
                expected_uid=1001)


    def test_worker_daemon_comparison_preserves_process_witness(self):
        """A new PID/start tick with the same nine-worker count must block."""
        from unittest.mock import patch
        from types import SimpleNamespace
        import sys
        from copy import deepcopy
        probe = module._load(
            "dsm928_worker_daemon_witness_contract",
            "game-uptime-live-daemon-identity.py",
        )
        names = (
            "scheduler_worker", "automation_worker", "content_update_worker",
            "maintenance_worker", "observability_retention_worker",
            "content_upload_retention_worker", "database_intelligence_worker",
            "hybrid_agent_worker", "hybrid_customer_workspace_worker",
        )
        witness = {
            "status": "local_identity_verified_only",
            "supervisor_verified": True, "workers_verified": True,
            "supervisor": {"pid": 100, "start_ticks": 200, "uid": 1001},
            "workers": {
                name: {"pid": 101 + i, "start_ticks": 201 + i,
                       "lock_status": "unverified"}
                for i, name in enumerate(names)
            },
        }
        fake = SimpleNamespace(inspect=lambda **kwargs: deepcopy(witness))
        with patch.dict(sys.modules, {"worker_identity_diagnostic": fake}):
            before = probe._workers_identity()
            controller = {"identity_verified": True, "pid": 42}
            def sample(group):
                return {"controller": controller, "worker_group": group,
                        "live_no_drain_authorized": False}
            self.assertTrue(before["all_nine_workers_verified"])
            self.assertEqual(len(before["worker_identities"]), 9)
            stable = probe.compare_installed_daemon_observations(
                sample(before), sample(probe._workers_identity()))
            self.assertTrue(stable["identity_snapshots_stable"])
            self.assertFalse(stable["live_no_drain_authorized"])
            witness["workers"]["scheduler_worker"]["lock_status"] = "busy"
            self.assertEqual(before, probe._workers_identity())
            witness["workers"]["scheduler_worker"]["start_ticks"] += 1
            changed = probe.compare_installed_daemon_observations(
                sample(before), sample(probe._workers_identity()))
            self.assertFalse(changed["identity_snapshots_stable"])
            self.assertIn("worker_group_identity_changed", changed["blockers"])
            witness["supervisor"]["pid"] = 999
            self.assertNotEqual(before, probe._workers_identity())
            missing = {k: v for k, v in before.items()
                       if k != "worker_identities"}
            blocked = probe.compare_installed_daemon_observations(
                sample(missing), sample(missing))
            self.assertFalse(blocked["identity_snapshots_stable"])
            self.assertFalse(blocked["live_no_drain_authorized"])


if __name__ == "__main__":
    unittest.main()
