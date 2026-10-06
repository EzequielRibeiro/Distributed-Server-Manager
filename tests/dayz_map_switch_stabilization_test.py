#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import dayz_operation_client


class DayZMapSwitchStabilizationTest(unittest.TestCase):
    def test_rejects_process_restart_even_if_runtime_is_running_again(self):
        views = [
            {
                "observed_state": "running",
                "adapter_state": {
                    "main_pid": 100,
                    "restart_count": 0,
                    "result": "success",
                },
            },
            {
                "observed_state": "running",
                "adapter_state": {
                    "main_pid": 101,
                    "restart_count": 0,
                    "result": "success",
                },
            },
        ]
        with (
            patch.dict(os.environ, {"CAPIVARA_DAYZ_SWITCH_STABILIZE_SECONDS": "1"}),
            patch.object(dayz_operation_client, "status", side_effect=views),
            patch.object(dayz_operation_client.time, "monotonic", side_effect=[0.0, 0.0, 0.5, 0.6]),
            patch.object(dayz_operation_client.time, "sleep", return_value=None),
        ):
            with self.assertRaisesRegex(RuntimeError, "restarted during map-switch stabilization"):
                dayz_operation_client._stabilize({}, "dayz-1")

    def test_rejects_systemd_oom_result_before_reporting_success(self):
        view = {
            "observed_state": "running",
            "adapter_state": {
                "main_pid": 100,
                "restart_count": 0,
                "result": "oom-kill",
            },
        }
        with (
            patch.dict(os.environ, {"CAPIVARA_DAYZ_SWITCH_STABILIZE_SECONDS": "1"}),
            patch.object(dayz_operation_client, "status", return_value=view),
            patch.object(dayz_operation_client.time, "monotonic", side_effect=[0.0, 0.0]),
        ):
            with self.assertRaisesRegex(RuntimeError, "systemd result oom-kill"):
                dayz_operation_client._stabilize({}, "dayz-1")

    def test_runtime_identity_reads_systemd_process_fields(self):
        pid, restarts, result = dayz_operation_client._runtime_identity({
            "adapter_state": {
                "main_pid": "4321",
                "restart_count": "2",
                "result": "success",
            }
        })
        self.assertEqual(pid, 4321)
        self.assertEqual(restarts, 2)
        self.assertEqual(result, "success")

    def test_activation_order_is_reported_in_projected_snapshot_order(self):
        snapshot = {
            "entries": [
                {"content_id": "cf", "game_id": "dayz", "package_id": "221100:1559212036", "activation_order": 10},
                {"content_id": "vpp", "game_id": "dayz", "package_id": "221100:1828439124", "activation_order": 20},
                {"content_id": "codelock", "game_id": "dayz", "package_id": "221100:1646187754", "activation_order": 30},
            ]
        }
        self.assertEqual(
            [item["content_id"] for item in dayz_operation_client._activation_order(snapshot)],
            ["cf", "vpp", "codelock"],
        )

    def test_prepared_disabled_map_is_exposed_as_community_source(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);managed=root/"managed";mission=managed/"V5.9"/"empty.deerisle";mission.mkdir(parents=True)
            (mission/"init.c").write_text("void main(){}",encoding="utf-8");(mission/"cfgeconomycore.xml").write_text("<economy/>",encoding="utf-8")
            state_root=root/"state";instance=state_root/"dayz-1";instance.mkdir(parents=True)
            state={"status":"applied","desired_state":"installed","activation_state":"disabled","game_id":"dayz","content_type":"map","security_state":"clean","installed_version":"latest","managed_path":str(managed),"content_id":"dayz-map:deerisle","community_map":{"mission_path":"V5.9/empty.deerisle","name":"Deer Isle"}}
            (instance/"dayz-map:deerisle.json").write_text(json.dumps(state),encoding="utf-8")
            with patch.object(dayz_operation_client,"CONTENT_STATE",state_root):
                record=dayz_operation_client._record_with_prepared_maps({},"dayz-1")
            self.assertEqual(record["content_dayz_community_missions"],[{"id":"empty.deerisle","source":str(mission.resolve()),"content_id":"dayz-map:deerisle","name":"Deer Isle"}])

    def test_removed_managed_map_is_not_preserved_from_runtime_projection(self):
        with tempfile.TemporaryDirectory() as td:
            state_root=Path(td)/"state";(state_root/"dayz-1").mkdir(parents=True)
            stale={"content_dayz_community_missions":[{"id":"empty.deerisle","source":"/stale/deerisle","content_id":"dayz-map:deerisle","name":"Deer Isle"}]}
            with patch.object(dayz_operation_client,"CONTENT_STATE",state_root):
                record=dayz_operation_client._record_with_prepared_maps(stale,"dayz-1")
            self.assertNotIn("content_dayz_community_missions",record)
            self.assertNotIn("_dayz_prepared_map_content",record)

    def test_unmanaged_community_mission_is_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            state_root=Path(td)/"state";(state_root/"dayz-1").mkdir(parents=True)
            unmanaged={"id":"custom.mission","source":"/srv/custom.mission","name":"Custom"}
            with patch.object(dayz_operation_client,"CONTENT_STATE",state_root):
                record=dayz_operation_client._record_with_prepared_maps({"content_dayz_community_missions":[unmanaged]},"dayz-1")
            self.assertEqual(record["content_dayz_community_missions"],[unmanaged])

    def test_same_configured_mission_reconciles_running_runtime(self):
        view={"current":"empty.deerisle","missions":[{"id":"empty.deerisle","can_activate":True,"active":True}]}
        with (
            patch.object(dayz_operation_client,"_record_with_prepared_maps",return_value={}),
            patch.object(dayz_operation_client,"discover_missions",return_value=view),
            patch.object(dayz_operation_client,"activation_snapshot",return_value={"entries":[]}),
            patch.object(dayz_operation_client,"mod_compatibility_preflight",return_value={"blocking":False,"items":[]}),
            patch.object(dayz_operation_client,"status",return_value={"observed_state":"running"}),
            patch.object(dayz_operation_client,"project_runtime_spec",return_value={}) as project,
            patch.object(dayz_operation_client.privileged_materialization,"materialize") as materialize,
            patch.object(dayz_operation_client,"lifecycle") as lifecycle,
            patch.object(dayz_operation_client,"_stabilize",return_value={"observed_state":"running"}) as stabilize,
        ):
            result=dayz_operation_client._change_mission({},{},"dayz-1",{"mission":"empty.deerisle","content_mode":"disable","persistence_mode":"fresh"})
        self.assertEqual([call.args[2] for call in lifecycle.call_args_list],["stop","start"])
        stabilize.assert_called_once_with({},"dayz-1")
        self.assertTrue(result["restarted"])
        self.assertTrue(result["reconciled"])
        self.assertFalse(result["changed"])

    def test_same_configured_community_mission_materializes_required_content_before_restart(self):
        view={"current":"empty.deerisle","missions":[{"id":"empty.deerisle","content_id":"dayz-map:deerisle","can_activate":True,"active":True}]}
        record={"_dayz_prepared_map_content":{"empty.deerisle":["dayz-map:deerisle","steam-workshop:123"]}}
        snapshot={"entries":[{"content_id":"steam-workshop:123"}]}
        projected={"runtime_spec":{"mods":["steam-workshop:123"]}}
        with (
            patch.object(dayz_operation_client,"_record_with_prepared_maps",return_value=record),
            patch.object(dayz_operation_client,"discover_missions",return_value=view),
            patch.object(dayz_operation_client,"activation_snapshot_with",return_value=snapshot) as snapshot_with,
            patch.object(dayz_operation_client,"mod_compatibility_preflight",return_value={"blocking":False,"items":[]}),
            patch.object(dayz_operation_client,"status",return_value={"observed_state":"running"}),
            patch.object(dayz_operation_client,"project_runtime_spec",return_value=projected) as project,
            patch.object(dayz_operation_client.privileged_materialization,"materialize") as materialize,
            patch.object(dayz_operation_client,"lifecycle") as lifecycle,
            patch.object(dayz_operation_client,"_stabilize",return_value={"observed_state":"running"}),
        ):
            result=dayz_operation_client._change_mission({},{},"dayz-1",{"mission":"empty.deerisle","content_mode":"disable","persistence_mode":"fresh"})
        snapshot_with.assert_called_once_with("dayz-1",["dayz-map:deerisle","steam-workshop:123"])
        projected_record=project.call_args.args[0]
        self.assertFalse(projected_record["dayz_content_enabled"])
        self.assertEqual(projected_record["dayz_required_content_ids"],["steam-workshop:123"])
        materialize.assert_called_once_with({},projected)
        self.assertEqual([call.args[2] for call in lifecycle.call_args_list],["stop","start"])
        self.assertTrue(result["reconciled"])

    def test_same_configured_mission_remains_noop_when_runtime_is_stopped(self):
        view={"current":"empty.deerisle","missions":[{"id":"empty.deerisle","can_activate":True,"active":True}]}
        with (
            patch.object(dayz_operation_client,"_record_with_prepared_maps",return_value={}),
            patch.object(dayz_operation_client,"discover_missions",return_value=view),
            patch.object(dayz_operation_client,"activation_snapshot",return_value={"entries":[]}),
            patch.object(dayz_operation_client,"mod_compatibility_preflight",return_value={"blocking":False,"items":[]}),
            patch.object(dayz_operation_client,"status",return_value={"observed_state":"stopped"}),
            patch.object(dayz_operation_client,"lifecycle") as lifecycle,
        ):
            result=dayz_operation_client._change_mission({},{},"dayz-1",{"mission":"empty.deerisle","content_mode":"disable","persistence_mode":"fresh"})
        lifecycle.assert_not_called()
        self.assertFalse(result["restarted"])
        self.assertFalse(result["changed"])

    def test_hybrid_rollback_repairs_file_access_through_privileged_helper(self):
        completed = type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        with (
            patch.dict(
                os.environ,
                {"CAPIVARA_MATERIALIZER_UNIT_TEMPLATE": "dsm-hybrid-agent-materialize@{instance_id}.service"},
                clear=False,
            ),
            patch.object(dayz_operation_client.subprocess, "run", return_value=completed) as run,
        ):
            unit = dayz_operation_client._repair_hybrid_file_access("dayz-1")
        self.assertEqual(unit, "dsm-hybrid-agent-files-access@dayz-1.service")
        run.assert_called_once_with(
            ["systemctl", "start", "dsm-hybrid-agent-files-access@dayz-1.service", "--no-pager"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def test_non_hybrid_rollback_does_not_require_file_access_helper(self):
        with (
            patch.dict(os.environ, {"CAPIVARA_MATERIALIZER_UNIT_TEMPLATE": "capivara-agent-materialize@{instance_id}.service"}, clear=False),
            patch.object(dayz_operation_client.subprocess, "run") as run,
        ):
            unit = dayz_operation_client._repair_hybrid_file_access("dayz-1")
        self.assertIsNone(unit)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
