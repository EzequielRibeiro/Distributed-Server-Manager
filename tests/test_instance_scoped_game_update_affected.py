"""Shared installation identity must control which instances are affected."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.linux.runtime import server_update_agent


class AffectedInstallationsTests(unittest.TestCase):
    def test_distinct_game_directories_do_not_share_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "dayz-1"
            second = Path(temporary) / "dayz-2"
            first.mkdir()
            second.mkdir()
            records = {
                "one": {"instance_id": "one", "agent_id": "agent", "game_id": "dayz",
                        "working_directory": str(first)},
                "two": {"instance_id": "two", "agent_id": "agent", "game_id": "dayz",
                        "working_directory": str(second)},
                "three": {"instance_id": "three", "agent_id": "agent", "game_id": "dayz",
                          "working_directory": str(first)},
            }
            with patch.object(server_update_agent.instance_runtime, "get_instance",
                              side_effect=records.get), patch.object(
                                  server_update_agent.instance_runtime, "list_instances",
                                  return_value=list(records.values())):
                self.assertEqual(server_update_agent._affected({"agent_id": "agent"}, "dayz",
                                                               first, "one"), ["one", "three"])

    def test_unknown_installation_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "dayz"
            target.mkdir()
            records = {
                "one": {"instance_id": "one", "agent_id": "agent", "game_id": "dayz",
                        "working_directory": str(target)},
                "two": {"instance_id": "two", "agent_id": "agent", "game_id": "dayz"},
            }
            with patch.object(server_update_agent.instance_runtime, "get_instance",
                              side_effect=records.get), patch.object(
                                  server_update_agent.instance_runtime, "list_instances",
                                  return_value=list(records.values())):
                with self.assertRaises(server_update_agent.ServerUpdateError):
                    server_update_agent._affected({"agent_id": "agent"}, "dayz", target, "one")


    def test_perform_update_rejects_foreign_agent_before_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "dayz"
            target.mkdir()
            config_file = root / "agent.json"
            config_file.write_text('{"agent_id": "local-agent"}', encoding="utf-8")
            foreign = {"instance_id": "foreign", "agent_id": "other-agent", "game_id": "dayz",
                       "working_directory": str(target)}
            selection = {"game": "dayz", "_server_update": {"instance_id": "foreign"}}
            with patch.object(server_update_agent.instance_runtime, "get_instance",
                              return_value=foreign), patch.dict("os.environ", {"CAPIVARA_AGENT_CONFIG": str(config_file)}), patch.object(
                                  server_update_agent, "detect_update") as detector:
                with self.assertRaises(server_update_agent.ServerUpdateError):
                    server_update_agent.perform_update(selection, target, lambda destination: None)
                detector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
