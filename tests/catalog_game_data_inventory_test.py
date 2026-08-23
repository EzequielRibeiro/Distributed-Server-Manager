#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "dashboard" / "catalog_game_data_inventory_http.py"
SPEC = importlib.util.spec_from_file_location("catalog_game_data_inventory_http", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeRepository:
    def __init__(self, backend):
        self.backend = backend

    def initialize(self):
        return None

    def list_for_agent(self, agent_id, limit=200):
        self.agent_id = agent_id
        return [
            {
                "job_id": "job-3",
                "agent_id": agent_id,
                "action": "verify",
                "environment_id": "minecraft.java.vanilla",
                "status": "running",
                "last_error": None,
            },
            {
                "job_id": "job-2",
                "agent_id": agent_id,
                "action": "install",
                "environment_id": "minecraft.java.vanilla",
                "status": "completed",
                "completed_at": "2026-08-23T16:00:00Z",
                "selection": {"game": "minecraft", "provider": "steam", "version": "1.21"},
                "result": {"game": "minecraft", "provider": "steam", "version": "1.21", "target_path": "/srv/game-data/minecraft/serverfiles"},
            },
            {
                "job_id": "job-1",
                "agent_id": agent_id,
                "action": "install",
                "environment_id": "dayz.stable",
                "status": "failed",
                "last_error": "authentication required",
            },
        ]


class CatalogGameDataInventoryTest(unittest.TestCase):
    def test_admin_sees_last_confirmed_install_and_latest_state(self):
        with mock.patch.object(MODULE, "AgentGameDataRepository", FakeRepository):
            status, body = MODULE.dispatch_catalog_game_data_inventory_get(
                MODULE.GAME_DATA_INVENTORY_PATH,
                "agent_id=agent-1",
                user={"role": "admin"},
                backend=object(),
            )
        self.assertEqual(status, 200)
        self.assertEqual(body["agent_id"], "agent-1")
        self.assertEqual(body["installed_count"], 1)
        self.assertEqual(body["active_jobs"], 1)
        item = body["items"][0]
        self.assertEqual(item["environment_id"], "minecraft.java.vanilla")
        self.assertEqual(item["version"], "1.21")
        self.assertEqual(item["latest_status"], "running")
        self.assertTrue(item["target_path"].endswith("/minecraft/serverfiles"))

    def test_non_admin_is_forbidden(self):
        status, body = MODULE.dispatch_catalog_game_data_inventory_get(
            MODULE.GAME_DATA_INVENTORY_PATH,
            "agent_id=agent-1",
            user={"role": "controller"},
            backend=object(),
        )
        self.assertEqual(status, 403)
        self.assertEqual(body["error"], "forbidden")

    def test_agent_id_is_required(self):
        status, body = MODULE.dispatch_catalog_game_data_inventory_get(
            MODULE.GAME_DATA_INVENTORY_PATH,
            "",
            user={"role": "admin"},
            backend=object(),
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
