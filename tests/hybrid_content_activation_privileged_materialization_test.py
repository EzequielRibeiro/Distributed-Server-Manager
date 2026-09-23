#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import content_activation_apply as module
import privileged_materialization


class HybridContentActivationPrivilegedMaterializationTest(unittest.TestCase):
    def _previous(self):
        return {
            "instance_id": "cli-000001-dayz-001",
            "agent_id": "agent-horizon-server",
            "runtime_id": "dayz.stable",
            "adapter": "systemd",
            "working_directory": "/opt/dsm/runtime/hybrid-agent-state/game-data/dayz/serverfiles",
            "executable": "/opt/dsm/runtime/hybrid-agent-state/game-data/dayz/serverfiles/DayZServer",
            "content_activation_checksum": "old",
        }

    def _snapshot(self):
        return {
            "instance_id": "cli-000001-dayz-001",
            "checksum": "new",
            "entries": [],
        }

    def test_activation_uses_privileged_materializer_after_content_files(self):
        previous = self._previous()
        projected = {**previous, "content_activation_checksum": "new"}
        config = {"agent_id": "agent-horizon-server"}

        with (
            patch.object(module.instance_runtime, "_owned", return_value=previous),
            patch.object(module.instance_runtime, "status", return_value={"observed_state": "stopped"}),
            patch.object(module.instance_runtime, "register_instance"),
            patch.object(module, "project_runtime_spec", return_value=projected),
            patch.object(module, "materialize_content_activation") as files,
            patch.object(module.privileged_materialization, "materialize") as privileged,
        ):
            result = module.apply_activation_snapshots(config, [self._snapshot()])

        self.assertTrue(result[0]["changed"])
        files.assert_called_once_with(projected)
        privileged.assert_called_once_with(config, projected)

    def test_activation_rollback_also_uses_privileged_materializer(self):
        previous = self._previous()
        projected = {**previous, "content_activation_checksum": "new"}
        config = {"agent_id": "agent-horizon-server"}

        with (
            patch.object(module.instance_runtime, "_owned", return_value=previous),
            patch.object(module.instance_runtime, "status", return_value={"observed_state": "stopped"}),
            patch.object(module.instance_runtime, "register_instance"),
            patch.object(module, "project_runtime_spec", return_value=projected),
            patch.object(module, "materialize_content_activation"),
            patch.object(
                module.privileged_materialization,
                "materialize",
                side_effect=[PermissionError("first apply failed"), {"operation": {"changed": True}}],
            ) as privileged,
        ):
            with self.assertRaisesRegex(module.ContentActivationApplyError, "first apply failed"):
                module.apply_activation_snapshots(config, [self._snapshot()])

        self.assertEqual(
            privileged.call_args_list,
            [call(config, projected), call(config, previous)],
        )


    def test_privileged_materialization_projects_activation_before_root_helper(self):
        spec = {
            "instance_id": "cli-000001-minecraft-001",
            "agent_id": "agent-horizon-server",
            "adapter": "systemd",
        }
        snapshot = {
            "instance_id": spec["instance_id"],
            "checksum": "bundle-checksum",
            "entries": [{"game_id": "minecraft"}],
        }
        projected = {
            **spec,
            "content_bundle_overrides": [
                {
                    "content_id": "modpack:test",
                    "managed_path": "/runtime/content/modpack-test",
                    "roots": ["overrides"],
                }
            ],
        }
        config = {"agent_id": "agent-horizon-server"}

        with (
            patch.object(privileged_materialization, "activation_snapshot", return_value=snapshot) as activation,
            patch.object(privileged_materialization, "project_runtime_spec", return_value=projected) as project,
            patch.object(privileged_materialization, "validate_runtime_spec", side_effect=lambda value, expected_agent_id=None: value),
            patch.object(privileged_materialization, "_invoke", return_value={"changed": True}) as invoke,
            patch.object(privileged_materialization.instance_runtime, "register_instance", return_value=projected),
            patch.object(privileged_materialization, "emit_runtime_event", return_value={}),
        ):
            privileged_materialization.materialize(config, spec)

        activation.assert_called_once_with(spec["instance_id"])
        project.assert_called_once_with(spec, snapshot)
        invoke.assert_called_once_with("apply", projected)


if __name__ == "__main__":
    unittest.main()
