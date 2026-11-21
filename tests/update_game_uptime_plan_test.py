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

    def test_runtime_change_requires_drain(self):
        self.put("agents/linux/runtime/agent.py","old","new")
        state=plan.analyze(self.installed,self.target)
        self.assertTrue(state["requires_game_drain"])
        self.assertFalse(state["live_no_drain_authorized"])

    def test_unit_change_requires_drain(self):
        self.put("systemd/capivara-instance@.service","old","new")
        self.assertTrue(plan.analyze(self.installed,self.target)["requires_game_drain"])

    def test_safe_cosmetic_candidate_never_authorizes_update(self):
        self.put("dashboard/web/style.css","old","new")
        state=plan.analyze(self.installed,self.target)
        self.assertEqual(state["classification"],"review_only")
        self.assertFalse(state["live_no_drain_authorized"])

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
