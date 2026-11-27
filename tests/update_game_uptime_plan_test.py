"""Fail-closed, read-only preflight update change classifier tests."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"update-manager"))
from importlib.machinery import SourceFileLoader

# Hyphenated helper path is intentionally used by the updater.
from importlib.util import spec_from_loader, module_from_spec
loader=SourceFileLoader("game_uptime_plan",str(ROOT/"update-manager/game-uptime-plan.py"))
spec=spec_from_loader(loader.name,loader)
plan=module_from_spec(spec)
loader.exec_module(plan)


class UptimeImpactTest(unittest.TestCase):
    def setUp(self):
        self.workspace=tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.installed=Path(self.workspace.name)/"installed"
        self.target=Path(self.workspace.name)/"target"
        self.installed.mkdir();self.target.mkdir()

    def put(self,path,old,new):
        for root,data in ((self.installed,old),(self.target,new)):
            p=root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)

    def test_signed_baseline_view_preserves_only_reviewed_local_state(self):
        import hashlib
        self.put("release-manifest.json", "old manifest", "new manifest")
        self.put("dashboard/web/status.css", "old", "new")
        self.put("agents/linux/installer/install-agent.sh", "script", "script")
        (self.installed / "agents/linux/installer/install-agent.sh").chmod(0o744)
        (self.target / "agents/linux/installer/install-agent.sh").chmod(0o644)
        self.put("config/agent.conf", "local config", "default config")
        old, new = plan._inventory(self.installed), plan._inventory(self.target)
        baseline = dict(old)
        baseline["config/agent.conf"] = new["config/agent.conf"]
        baseline["agents/linux/installer/install-agent.sh"] = new["agents/linux/installer/install-agent.sh"]
        path = self.installed / "backups/example.py"
        path.parent.mkdir()
        path.write_text("historical backup")
        old = plan._inventory(self.installed)
        adjusted, counts = plan._reconcile_signed_baseline(
            self.installed, old, baseline, new,
            {"config/agent.conf": old["config/agent.conf"]})
        self.assertEqual({k for k in old.keys() | adjusted.keys()
                          if old.get(k) != adjusted.get(k)},
                         {"release-manifest.json", "dashboard/web/status.css"})
        self.assertEqual(counts["installer_execute_mode"], 1)
        self.assertEqual(counts["preserved_data"], 1)
        self.assertEqual(counts["reviewed_local_configuration"], 1)
        with self.assertRaisesRegex(ValueError, "unreviewed installed baseline drift"):
            plan._reconcile_signed_baseline(self.installed, old, baseline, new, {})
        changed_config = dict(new)
        changed_config["config/agent.conf"] = (0o644, hashlib.sha256(b"new").hexdigest())
        with self.assertRaisesRegex(ValueError, "drift on changed release path"):
            plan._reconcile_signed_baseline(self.installed, old, baseline, changed_config,
                                            {"config/agent.conf": old["config/agent.conf"]})

    def test_signed_baseline_rejects_unexpected_product_drift_even_if_matches_target(self):
        self.put("release-manifest.json", "old", "new")
        self.put("dashboard/web/style.css", "old", "new")
        baseline = plan._inventory(self.installed)
        (self.installed / "dashboard/web/style.css").write_text("new")
        with self.assertRaisesRegex(ValueError, "drift on changed release path"):
            plan._reconcile_signed_baseline(
                self.installed, plan._inventory(self.installed), baseline,
                plan._inventory(self.target), {})

    def test_signed_baseline_rejects_unverified_and_changed_source_caches(self):
        import py_compile
        self.put("release-manifest.json", "old", "new")
        self.put("dashboard/example.py", "VALUE = 1", "VALUE = 1")
        baseline = plan._inventory(self.installed)
        cache = Path(py_compile.compile(str(self.installed / "dashboard/example.py"),
                                        doraise=True))
        actual = plan._inventory(self.installed)
        target = plan._inventory(self.target)
        adjusted, counts = plan._reconcile_signed_baseline(
            self.installed, actual, baseline, target, {})
        self.assertEqual(counts["verified_unchanged_python_cache"], 1)
        self.assertEqual(adjusted[cache.relative_to(self.installed).as_posix()],
                         actual[cache.relative_to(self.installed).as_posix()])
        (self.target / "dashboard/example.py").write_text("VALUE = 2")
        with self.assertRaisesRegex(ValueError, "unreviewed installed baseline drift"):
            plan._reconcile_signed_baseline(self.installed, actual, baseline,
                                            plan._inventory(self.target), {})
        cache.write_bytes(cache.read_bytes()[:-1] + b"!")
        with self.assertRaisesRegex(ValueError, "unreviewed installed baseline drift"):
            plan._reconcile_signed_baseline(self.installed, plan._inventory(self.installed),
                                            baseline, target, {})

    def test_unsigned_runtime_projections_are_not_product_drift(self):
        self.put("release-manifest.json", "old", "new")
        self.put("dashboard/web/status.css", "old", "new")
        baseline = plan._inventory(self.installed)
        target = plan._inventory(self.target)
        names = [
            "runtime/resources/node-123/dayz/cli-000001-dayz-002/server.json",
            "runtime/resources/node-123/dayz/cli-000001-dayz-002/metrics.json",
        ]
        for name in names:
            path = self.installed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"status": "online"}')
            path.chmod(0o644)
        signed = baseline.keys() | target.keys()
        actual = plan._inventory(self.installed, signed_paths=signed)
        self.assertEqual(actual, baseline)
        for name in names:
            (self.installed / name).write_text('{"status": "offline"}')
        self.assertEqual(plan._inventory(self.installed, signed_paths=signed), baseline)
        adjusted, _ = plan._reconcile_signed_baseline(
            self.installed, actual, baseline, target, {})
        self.assertEqual(adjusted, target)
        # Signed member paths and strict inventory are never filtered.
        self.assertIn(names[0], plan._inventory(self.installed))
        self.assertIn(names[0], plan._inventory(
            self.installed, signed_paths=signed | {names[0]}))
        # Unknown names, wrong depth and executable product remain visible.
        for name in ("runtime/resources/node-123/dayz/cli-000001-dayz-002/custom.py",
                     "runtime/resources/node-123/dayz/server.json",
                     "runtime/resources/node-123/dayz/cli-000001-dayz-002/other.json"):
            path = self.installed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unexpected")
            actual = plan._inventory(self.installed, signed_paths=signed)
            self.assertIn(name, actual)
            with self.assertRaisesRegex(ValueError, "unreviewed installed baseline drift"):
                plan._reconcile_signed_baseline(self.installed, actual, baseline, target, {})
            path.unlink()

    def test_unsafe_generated_runtime_projection_blocks(self):
        path = self.installed / "runtime/resources/node-123/dayz/instance/server.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        path.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "unsafe generated runtime projection"):
            plan._inventory(self.installed, signed_paths=set())
        path.chmod(0o644)
        alias = self.installed / "alias"
        alias.hardlink_to(path)
        with self.assertRaisesRegex(ValueError, "unsafe generated runtime projection"):
            plan._inventory(self.installed, signed_paths=set())
        alias.unlink()
        path.unlink()
        path.symlink_to("/nonexistent")
        with self.assertRaisesRegex(ValueError, "symlink"):
            plan._inventory(self.installed, signed_paths=set())

    def test_runtime_change_requires_drain(self):
        self.put("agents/linux/runtime/agent.py","old","new")
        state=plan.analyze(self.installed,self.target)
        self.assertTrue(state["requires_game_drain"])
        self.assertFalse(state["live_no_drain_authorized"])
        self.put("agents/linux/runtime/game_uptime_hold_coordinator.py", "old", "new")
        state = plan.analyze(self.installed, self.target)
        fixed = state["fixed_file_transaction_plan"]
        self.assertTrue(fixed["bootstrap_installation_required"])
        self.assertEqual(fixed["changed_paths"], [])
        self.assertIn("initial_fence_aware_installation_or_bootstrap_update_required",
                      fixed["blockers"])

    def test_unit_change_requires_drain(self):
        self.put("systemd/capivara-instance@.service","old","new")
        self.assertTrue(plan.analyze(self.installed,self.target)["requires_game_drain"])

    def test_safe_cosmetic_candidate_never_authorizes_update(self):
        self.put("dashboard/web/style.css","old","new")
        state=plan.analyze(self.installed,self.target)
        self.assertEqual(state["classification"],"review_only")
        self.assertFalse(state["live_no_drain_authorized"])
        self.put("version", "2.0.132", "2.0.133")
        self.put("release-manifest.json", "old manifest", "new manifest")
        fixed = plan.analyze(self.installed, self.target)["fixed_file_transaction_plan"]
        self.assertEqual(fixed["status"], "compatible_file_plan_only")
        self.assertEqual(fixed["changed_paths"],
                         ["dashboard/web/style.css", "release-manifest.json", "version"])
        self.assertFalse(fixed["live_no_drain_authorized"])
        (self.target/"dashboard/web/extra.css").write_text("extra")
        fixed = plan.analyze(self.installed, self.target)["fixed_file_transaction_plan"]
        self.assertEqual(fixed["status"], "blocked")
        self.assertEqual(fixed["changed_paths"], [])
        self.assertEqual(fixed["incompatible_file_count"], 1)

    def test_unknown_file_is_critical(self):
        self.put("new-module/loader.py","old","new")
        self.assertTrue(plan.analyze(self.installed,self.target)["requires_game_drain"])

    def test_protected_runtime_state_is_excluded(self):
        self.put("runtime/hybrid-instance-storage/private/world.dat","one","two")
        state=plan.analyze(self.installed,self.target)
        self.assertEqual(state["changed_count"],0)

    def test_steamcmd_runtime_home_is_excluded_but_other_symlinks_block(self):
        # Production-like SteamCMD layout: .steam/steam points at .local/share/Steam.
        for root in (self.installed, self.target):
            steam = root / ".steam"
            steam.mkdir()
            (steam / "steam").symlink_to(root / ".local/share/Steam")
            cache = root / ".local/share/Steam/appcache"
            cache.mkdir(parents=True)
            (cache / "state.bin").write_bytes(b"cache")
        state = plan.analyze(self.installed, self.target)
        self.assertEqual(state["changed_count"], 0)
        self.assertFalse(state["live_no_drain_authorized"])
        (self.target / "agents").mkdir()
        (self.target / "agents/unsafe").symlink_to(self.installed)
        with self.assertRaisesRegex(ValueError, "symlink"):
            plan.analyze(self.installed, self.target)

    def test_excluded_runtime_tree_is_pruned_before_scanning(self):
        # Even unreadable/broken links inside preserved game state are not
        # release payload; do not inspect them or descend into the tree.
        for root in (self.installed, self.target):
            for relative in ("runtime/hybrid-agent-state/private",
                             "runtime/state/private",
                             "runtime/artifact-transfers/job"):
                preserved = root / relative
                preserved.mkdir(parents=True)
                (preserved / "broken").symlink_to("/nonexistent-private-state")
                (preserved / "world.bin").write_bytes(b"state")
        state = plan.analyze(self.installed, self.target)
        self.assertEqual(state["changed_count"], 0)
        self.assertFalse(state["live_no_drain_authorized"])

    def test_symlink_fails_closed(self):
        (self.target/"unsafe").symlink_to(self.installed)
        with self.assertRaises(ValueError):
            plan.analyze(self.installed,self.target)



    def test_control_plane_worker_change_is_only_candidate_for_disposable_review(self):
        self.put("dashboard/workers/worker.py", "old", "new")
        state = plan.analyze(self.installed, self.target)
        self.assertEqual(state["change_tier"], "control_plane_restart_candidate")
        self.assertTrue(state["requires_game_drain"], "current updater still drains games")
        self.assertTrue(state["control_plane_candidate_for_disposable_review"])
        self.assertFalse(state["live_no_drain_authorized"])

    def test_added_controller_executable_and_mode_change_force_maintenance(self):
        self.put("dashboard/workers/worker.py", "old", "new")
        first = plan.analyze(self.installed, self.target)
        self.assertEqual(first["change_tier"], "control_plane_restart_candidate")
        (self.target / "dashboard/workers/new.py").write_text("new")
        second = plan.analyze(self.installed, self.target)
        self.assertEqual(second["change_tier"], "full_maintenance_required")
        (self.target / "dashboard/workers/new.py").unlink()
        (self.target / "dashboard/workers/worker.py").chmod(0o755)
        third = plan.analyze(self.installed, self.target)
        self.assertEqual(third["change_tier"], "full_maintenance_required")

    def test_game_adapter_requires_instance_maintenance(self):
        self.put("agents/linux/runtime/adapters/dayz.py", "old", "new")
        state = plan.analyze(self.installed, self.target)
        self.assertEqual(state["change_tier"], "instance_maintenance_required")
        self.assertFalse(state["control_plane_candidate_for_disposable_review"])

    def test_database_and_systemd_changes_require_full_maintenance(self):
        self.put("dashboard/web/status.css", "old", "new")
        self.put("database/migrations/0023.sql", "old", "new")
        self.put("systemd/capivara-instance@.service", "old", "new")
        state = plan.analyze(self.installed, self.target)
        self.assertEqual(state["change_tier"], "full_maintenance_required")
        self.assertFalse(state["control_plane_candidate_for_disposable_review"])

    def test_full_inventory_classification_not_only_truncated_preview(self):
        for i in range(65):
            self.put(f"dashboard/web/p{i:03d}.css", "old", "new")
        self.put("zz-unknown/surprise.py", "old", "new")
        state = plan.analyze(self.installed, self.target)
        self.assertEqual(state["change_tier"], "full_maintenance_required")
        self.assertEqual(state["change_tier_counts"]["control_plane_restart_candidate"], 65)
        self.assertEqual(state["change_tier_counts"]["full_maintenance_required"], 1)
        self.assertFalse(state["control_plane_candidate_for_disposable_review"])

    def test_docs_and_version_only_and_no_change_never_authorize(self):
        unchanged = plan.analyze(self.installed, self.target)
        self.assertEqual(unchanged["change_tier"], "no_change")
        self.assertFalse(unchanged["control_plane_candidate_for_disposable_review"])
        self.put("docs/howto.md", "old", "new")
        self.put("version", "2.0.132", "2.0.133")
        state = plan.analyze(self.installed, self.target)
        self.assertEqual(state["change_tier"], "restart_free")
        self.assertTrue(state["control_plane_candidate_for_disposable_review"])
        self.assertFalse(state["live_no_drain_authorized"])


if __name__=="__main__":
    unittest.main()
