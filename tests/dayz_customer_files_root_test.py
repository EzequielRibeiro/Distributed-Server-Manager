#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from profiles.dayz import DayZRuntimeProfile
from runtime_spec import validate_runtime_spec


class DayZCustomerFilesRootTest(unittest.TestCase):
    def test_dayz_exposes_private_instance_tree_to_customer_file_manager(self):
        profile = DayZRuntimeProfile()
        instance_id = "cli-000001-dayz-001"
        state_root = f"/var/lib/capivara-instances/{instance_id}"
        install_root = "/opt/dsm/game-data/dayz/serverfiles"

        spec = profile.build_runtime_spec(
            {
                "instance_id": instance_id,
                "agent_id": "agent-test",
                "environment_id": "dayz.stable",
                "runtime_id": "dayz.stable",
            },
            {
                "install_path": install_root,
                "instance_state_root": state_root,
                "ports": {
                    "game": {"port": 2302, "protocol": "udp"},
                    "game_aux": {"port": 2304, "protocol": "udp"},
            "battleye": {"port": 2306, "protocol": "udp"},
                    "steam_query": {"port": 2305, "protocol": "udp"},
                },
            },
        )

        self.assertEqual(profile.profile_version, 12)
        self.assertEqual(spec["working_directory"], install_root)
        self.assertEqual(spec["files_root"], state_root)
        self.assertEqual(spec["configuration_root"], f"{state_root}/config")
        self.assertNotEqual(spec["files_root"], spec["working_directory"])

        normalized = validate_runtime_spec(spec, expected_agent_id="agent-test")
        self.assertEqual(normalized["files_root"], state_root)

    def test_dayz_files_root_remains_instance_private_during_profile_migration(self):
        profile = DayZRuntimeProfile()
        record = {
            "instance_id": "cli-000001-dayz-001",
            "agent_id": "agent-test",
            "runtime_id": "dayz.stable",
            "working_directory": "/opt/dsm/game-data/dayz/serverfiles",
            "instance_state_root": "/var/lib/capivara-instances/cli-000001-dayz-001",
            "ports": {
                "game": {"port": 2302, "protocol": "udp"},
                "game_aux": {"port": 2304, "protocol": "udp"},
            "battleye": {"port": 2306, "protocol": "udp"},
                "steam_query": {"port": 2305, "protocol": "udp"},
            },
        }

        context = profile.migration_context(record)
        spec = profile.build_runtime_spec(record, context)

        self.assertEqual(
            spec["files_root"],
            "/var/lib/capivara-instances/cli-000001-dayz-001",
        )
        self.assertNotEqual(spec["files_root"], record["working_directory"])


if __name__ == "__main__":
    unittest.main()

def test_nasdara_mask_flows_profile_validation_and_systemd():
    from materializers.systemd import render_unit
    profile = DayZRuntimeProfile()
    install = "/opt/dsm/game-data/dayz/serverfiles"
    instance = {"instance_id": "cli-000001-dayz-001", "agent_id": "agent-test"}
    context = {
        "install_path": install,
        "instance_state_root": "/var/lib/capivara-instances/cli-000001-dayz-001",
        "mission": "hardcore.namalsk",
        "isolate_nasdara_for_non_nasdara": True,
        "ports": {"game": {"port": 2302, "protocol": "udp"},
                  "game_aux": {"port": 2304, "protocol": "udp"},
                  "battleye": {"port": 2306, "protocol": "udp"},
                  "steam_query": {"port": 2305, "protocol": "udp"}}
    }
    spec = validate_runtime_spec(profile.build_runtime_spec(instance, context))
    assert spec["inaccessible_content_paths"] == [install + "/nasdara"]
    assert "InaccessiblePaths=" + install + "/nasdara\n" in render_unit(spec)
    context["isolate_nasdara_for_non_nasdara"] = False
    spec = validate_runtime_spec(profile.build_runtime_spec(instance, context))
    assert "InaccessiblePaths=" not in render_unit(spec)
    context.update(isolate_nasdara_for_non_nasdara=True, mission="dayzOffline.nasdara")
    nasdara_spec = validate_runtime_spec(profile.build_runtime_spec(instance, context))
    assert nasdara_spec["inaccessible_content_paths"] == []
