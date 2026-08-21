#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import game_data_state
import local_cli


class AgentLocalGameDataStateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.temp.name) / "state"
        self.game_root = self.state_root / "game-data"
        self.job_root = self.state_root / "game-data-jobs"
        self.history_root = self.job_root / "history"
        self.game_state_root = self.state_root / "game-data-state"
        self.originals = {
            "STATE_ROOT": game_data_state.STATE_ROOT,
            "GAME_DATA_ROOT": game_data_state.GAME_DATA_ROOT,
            "JOB_ROOT": game_data_state.JOB_ROOT,
            "HISTORY_ROOT": game_data_state.HISTORY_ROOT,
            "GAME_STATE_ROOT": game_data_state.GAME_STATE_ROOT,
        }
        game_data_state.STATE_ROOT = self.state_root
        game_data_state.GAME_DATA_ROOT = self.game_root
        game_data_state.JOB_ROOT = self.job_root
        game_data_state.HISTORY_ROOT = self.history_root
        game_data_state.GAME_STATE_ROOT = self.game_state_root

        self.config_path = Path(self.temp.name) / "agent.json"
        self.config_path.write_text(json.dumps({
            "agent_id": "agent-one",
            "node_id": "node-one",
            "controller_url": "https://controller.example",
            "credential_id": "cred-one",
            "credential_secret": "secret-one",
            "fingerprint": "sha256:test",
        }), encoding="utf-8")
        self.original_config = local_cli.CONFIG_PATH
        local_cli.CONFIG_PATH = self.config_path

    def tearDown(self):
        for key, value in self.originals.items():
            setattr(game_data_state, key, value)
        local_cli.CONFIG_PATH = self.original_config
        self.temp.cleanup()

    def test_record_and_read_game_data_inventory(self):
        target = self.game_root / "dayz" / "serverfiles"
        target.mkdir(parents=True)
        (target / "DayZServer").write_text("binary", encoding="utf-8")
        state = game_data_state.record_game_data(
            job_id="game-data-123",
            action="install",
            selection={"game": "dayz", "provider": "steam", "version": "current"},
            result={"game": "dayz", "provider": "steam", "version": "current", "target_path": str(target)},
        )
        self.assertTrue(state["installed"])
        self.assertEqual(state["last_job_id"], "game-data-123")
        listed = game_data_state.list_game_data()
        self.assertEqual([item["game"] for item in listed], ["dayz"])
        status = game_data_state.get_game_data("dayz")
        self.assertTrue(status["path_exists"])
        self.assertTrue(status["path_nonempty"])

    def test_archive_job_preserves_sanitized_history(self):
        request, result, log = game_data_state.job_paths("game-data-abc")
        game_data_state.write_json(request, {
            "job_id": "game-data-abc",
            "action": "install",
            "environment_id": "dayz.stable",
            "selector": "current",
            "credential_secret": "must-not-survive",
            "selection": {"game": "dayz", "provider": "steam", "credential_secret": "also-secret"},
        })
        game_data_state.write_json(result, {
            "job_id": "game-data-abc",
            "status": "completed",
            "progress": 100,
            "game": "dayz",
            "provider": "steam",
            "target_path": str(self.game_root / "dayz" / "serverfiles"),
        })
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("done\n", encoding="utf-8")
        archived = game_data_state.archive_job("game-data-abc")
        self.assertEqual(archived["status"], "completed")
        raw = (self.history_root / "game-data-abc.json").read_text(encoding="utf-8")
        self.assertNotIn("must-not-survive", raw)
        self.assertNotIn("also-secret", raw)
        self.assertEqual(game_data_state.get_job("game-data-abc")["game"], "dayz")

    def test_list_jobs_combines_active_and_history(self):
        request, result, _ = game_data_state.job_paths("game-data-running")
        game_data_state.write_json(request, {
            "job_id": "game-data-running",
            "action": "install",
            "selection": {"game": "minecraft", "provider": "http"},
        })
        game_data_state.write_json(result, {"job_id": "game-data-running", "status": "running", "progress": 35})
        game_data_state.write_json(self.history_root / "game-data-old.json", {
            "job_id": "game-data-old",
            "status": "failed",
            "game": "dayz",
            "archived_at": "2026-08-20T00:00:00Z",
        })
        active = game_data_state.list_jobs(active_only=True)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["job_id"], "game-data-running")
        combined = game_data_state.list_jobs(limit=10)
        self.assertEqual({item["job_id"] for item in combined}, {"game-data-running", "game-data-old"})

    def test_local_cli_game_data_and_jobs_are_read_only_views(self):
        game = {"game": "dayz", "installed": True, "provider": "steam"}
        job = {"job_id": "game-data-1", "status": "completed", "active": False}
        with patch.object(local_cli, "list_game_data", return_value=[game]), patch.object(
            local_cli, "get_game_data", return_value=game
        ), patch.object(local_cli, "list_jobs", return_value=[job]), patch.object(
            local_cli, "get_job", return_value=job
        ):
            output = StringIO()
            with redirect_stdout(output):
                code = local_cli.main(["agent", "game-data", "list", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["games"][0]["game"], "dayz")

            output = StringIO()
            with redirect_stdout(output):
                code = local_cli.main(["agent", "jobs", "show", "game-data-1", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["job_id"], "game-data-1")

    def test_doctor_warns_on_recent_game_data_failure(self):
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        with patch.object(local_cli, "_service_state", return_value={"healthy": True}), patch.object(
            local_cli, "_controller_probe", return_value={"reachable": True}
        ), patch.object(local_cli, "detect_capabilities", return_value={}), patch.object(
            local_cli, "collect_network_inventory", return_value={"tcp_listen": [], "udp_listen": []}
        ), patch.object(local_cli, "_host", return_value={"storage_root_free_bytes": 20 * 1024**3}), patch.object(
            local_cli,
            "game_data_summary",
            return_value={"game_data_root": str(self.game_root), "installed_count": 1, "active_jobs": 0, "failed_recent_jobs": 1},
        ):
            result = local_cli._doctor(config)
        self.assertEqual(result["status"], "degraded")
        self.assertIn("recent_game_data_failures", {item["code"] for item in result["findings"]})


if __name__ == "__main__":
    unittest.main()
