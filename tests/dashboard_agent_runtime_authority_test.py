from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "dashboard" / "server.py"


def function_source(name: str, next_name: str) -> str:
    source = SERVER.read_text(encoding="utf-8")
    start = source.index(f"def {name}(")
    end = source.index(f"def {next_name}(", start)
    return source[start:end]


class DashboardAgentRuntimeAuthorityTest(unittest.TestCase):

    def test_runtime_summary_uses_agent_as_runtime_authority(self):
        source = function_source(
            "api_runtime_summary",
            "reinstall_instance_from_game_data",
        )

        self.assertIn(
            "AgentInstanceRuntimeHealthRepository",
            source,
        )
        self.assertIn(
            "list_for_agent",
            source,
        )
        self.assertIn(
            'item.get("observed_state")',
            source,
        )
        self.assertIn(
            'item.get("health")',
            source,
        )

        #
        # O Controller não pode consultar seu próprio SO
        # para determinar o estado de uma instância remota.
        #
        self.assertNotIn(
            "process.pid",
            source,
        )
        self.assertNotIn(
            "/proc/",
            source,
        )
        self.assertNotIn(
            "live_pid",
            source,
        )
        self.assertNotIn(
            "cmdline",
            source,
        )

    def test_instance_control_projects_agent_observed_state(self):
        source = function_source(
            "control_instance",
            "delete_instance",
        )

        self.assertIn(
            'result.get("observed_state")',
            source,
        )

        self.assertIn(
            'result.get("result", {}).get("observed_state")',
            source,
        )

        self.assertIn(
            'raw_state in {"running", "online"}',
            source,
        )

        self.assertIn(
            'raw_state in {"stopped", "offline"}',
            source,
        )

        self.assertIn(
            'raw_state == "failed"',
            source,
        )

        self.assertIn(
            'server_state["source"] = "agent"',
            source,
        )

        self.assertIn(
            "update_instance_status",
            source,
        )

    def test_controller_does_not_project_remote_pid(self):
        runtime_source = function_source(
            "api_runtime_summary",
            "reinstall_instance_from_game_data",
        )

        control_source = function_source(
            "control_instance",
            "delete_instance",
        )

        self.assertIn(
            'server_state["pid"] = None',
            runtime_source,
        )

        self.assertIn(
            'server_state["pid"] = None',
            control_source,
        )


if __name__ == "__main__":
    unittest.main()
