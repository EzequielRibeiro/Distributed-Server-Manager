import csv
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "database", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import agent_deploy_batch_cli


class AgentDeployBatchTest(unittest.TestCase):
    def csv_file(self, fields, rows):
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False)
        with handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def test_port_pool_and_location_are_forwarded_to_normal_deploy(self):
        path = self.csv_file(
            ["host", "ssh_user", "region_id", "datacenter_id", "port_range", "port_protocol"],
            [{"host": "node1.example", "ssh_user": "ops", "region_id": "br", "datacenter_id": "gru", "port_range": "24000-24999", "port_protocol": "both"}],
        )
        with mock.patch.object(agent_deploy_batch_cli.agent_deploy_cli, "deploy", return_value={"agent_id": "agent-1"}) as deploy:
            result = agent_deploy_batch_cli.run_batch(path)
        args = deploy.call_args.args[0]
        self.assertEqual(args.port_range, "24000-24999")
        self.assertEqual(args.port_protocol, "both")
        self.assertEqual(args.region_id, "br")
        self.assertEqual(args.datacenter_id, "gru")
        self.assertTrue(result["ok"])

    def test_plaintext_password_column_is_rejected(self):
        path = self.csv_file(["host", "ssh_user", "password"], [{"host": "node1", "ssh_user": "ops", "password": "secret"}])
        with self.assertRaisesRegex(ValueError, "unsupported columns"):
            agent_deploy_batch_cli.run_batch(path)

    def test_continue_on_error_processes_remaining_rows(self):
        path = self.csv_file(["host", "ssh_user"], [{"host": "one", "ssh_user": "ops"}, {"host": "two", "ssh_user": "ops"}])
        with mock.patch.object(agent_deploy_batch_cli.agent_deploy_cli, "deploy", side_effect=[RuntimeError("failed"), {"agent_id": "agent-2"}]):
            result = agent_deploy_batch_cli.run_batch(path, continue_on_error=True)
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["completed"], 1)


if __name__ == "__main__":
    unittest.main()
