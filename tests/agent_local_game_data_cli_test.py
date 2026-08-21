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

import game_data_client
import game_data_state
import local_cli


class AgentLocalGameDataCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state_root = Path(self.temp.name) / "state"
        self.job_root = self.state_root / "game-data-jobs"
        self.history_root = self.job_root / "history"
        self.game_state_root = self.state_root / "game-data-state"
        self.game_root = self.state_root / "game-data"
        self.config_path = Path(self.temp.name) / "agent.json"
        self.config_path.write_text(
            json.dumps({
                "agent_id": "agent-one",
                "node_id": "node-one",
                "controller_url": "https://controller.example",
                "credential_id": "cred-one",
                "credential_secret": "secret-one",
                "fingerprint": "sha256:test",
            }),
            encoding="utf-8",
        )

        self.originals = {
            "state_JOB_ROOT": game_data_state.JOB_ROOT,
            "state_HISTORY_ROOT": game_data_state.HISTORY_ROOT,
            "state_GAME_STATE_ROOT": game_data_state.GAME_STATE_ROOT,
            "state_GAME_DATA_ROOT": game_data_state.GAME_DATA_ROOT,
            "client_JOB_ROOT": game_data_client.JOB_ROOT,
            "cli_CONFIG_PATH": local_cli.CONFIG_PATH,
        }
        game_data_state.JOB_ROOT = self.job_root
        game_data_state.HISTORY_ROOT = self.history_root
        game_data_state.GAME_STATE_ROOT = self.game_state_root
        game_data_state.GAME_DATA_ROOT = self.game_root
        game_data_client.JOB_ROOT = self.job_root
        local_cli.CONFIG_PATH = self.config_path

    def tearDown(self):
        game_data_state.JOB_ROOT = self.originals["state_JOB_ROOT"]
        game_data_state.HISTORY_ROOT = self.originals["state_HISTORY_ROOT"]
        game_data_state.GAME_STATE_ROOT = self.originals["state_GAME_STATE_ROOT"]
        game_data_state.GAME_DATA_ROOT = self.originals["state_GAME_DATA_ROOT"]
        game_data_client.JOB_ROOT = self.originals["client_JOB_ROOT"]
        local_cli.CONFIG_PATH = self.originals["cli_CONFIG_PATH"]
        self.temp.cleanup()

    def _completed_job(self, job_id: str = "game-data-test") -> None:
        request, result, log = game_data_state.job_paths(job_id)
        game_data_state.write_json(request, {
            "job_id": job_id,
            "action": "install",
            "environment_id": "dayz.stable",
            "selector": "stable",
            "selection": {
                "game": "dayz",
                "provider": "steam",
                "version": "1.0",
                "credential_secret": "must-not-be-archived",
            },
        })
        game_data_state.write_json(result, {
            "job_id": job_id,
            "status": "completed",
            "progress": 100,
            "game": "dayz",
            "provider": "steam",
            "version": "1.0",
            "target_path": str(self.game_root / "dayz" / "serverfiles"),
        })
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("completed\n", encoding="utf-8")

    def test_ack_archives_sanitized_job_before_transient_cleanup(self):
        self._completed_job()
        game_data_client.clear_game_data_result("game-data-test")

        request, result, _ = game_data_state.job_paths("game-data-test")
        self.assertFalse(request.exists())
        self.assertFalse(result.exists())
        archived = game_data_state.get_job("game-data-test")
        self.assertIsNotNone(archived)
        self.assertEqual(archived["status"], "completed")
        self.assertEqual(archived["game"], "dayz")
        self.assertNotIn("selection", archived)
        self.assertNotIn("credential_secret", json.dumps(archived))

    def test_game_inventory_is_persistent_and_reports_path_health(self):
        target = self.game_root / "dayz" / "serverfiles"
        target.mkdir(parents=True)
        (target / "server.bin").write_text("ok", encoding="utf-8")
        game_data_state.record_game_data(
            job_id="game-data-test",
            action="install",
            selection={"game": "dayz", "provider": "steam", "version": "1.0"},
            result={
                "game": "dayz",
                "provider": "steam",
                "version": "1.0",
                "target_path": str(target),
            },
        )
        status = game_data_state.get_game_data("dayz")
        self.assertTrue(status["installed"])
        self.assertTrue(status["path_exists"])
        self.assertTrue(status["path_nonempty"])
        self.assertEqual(game_data_state.list_game_data()[0]["last_job_id"], "game-data-test")

    def test_cli_game_data_list_and_jobs_show_are_read_only(self):
        with patch.object(local_cli, "list_game_data", return_value=[{"game": "dayz", "installed": True}]):
            output = StringIO()
            with redirect_stdout(output):
                code = local_cli.main(["agent", "game-data", "list", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["games"][0]["game"], "dayz")

        with patch.object(local_cli, "get_job", return_value={"job_id": "job-1", "status": "completed", "active": False}):
            output = StringIO()
            with redirect_stdout(output):
                code = local_cli.main(["agent", "jobs", "show", "job-1", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["job_id"], "job-1")

    def test_doctor_warns_on_recent_failed_game_data_job(self):
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        with patch.object(local_cli, "_service_state", return_value={"healthy": True}), patch.object(
            local_cli, "_controller_probe", return_value={"reachable": True}
        ), patch.object(local_cli, "detect_capabilities", return_value={}), patch.object(
            local_cli, "_ports", return_value={"configured": True, "conflict_count": 0}
        ), patch.object(local_cli, "_host", return_value={"storage_root_free_bytes": 20 * 1024**3}), patch.object(
            local_cli,
            "game_data_summary",
            return_value={"installed_count": 1, "active_jobs": 0, "failed_recent_jobs": 1},
        ):
            result = local_cli._doctor(config)
        self.assertEqual(result["status"], "degraded")
        self.assertIn("recent_game_data_failures", {item["code"] for item in result["findings"]})


if __name__ == "__main__":
    unittest.main()
