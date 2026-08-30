from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

import controller_service_health


class ControllerServiceTopologyTest(unittest.TestCase):
    def test_consolidated_worker_has_no_retired_daemon_dependencies(self):
        text = (ROOT / "systemd" / "dsm-dashboard-worker.service").read_text(encoding="utf-8")
        self.assertNotIn("dsm-monitor.service", text)
        self.assertNotIn("dsm-scheduler.service", text)

    def test_dashboard_requires_topology_and_wants_workers(self):
        text = (ROOT / "systemd" / "dsm-dashboard.service").read_text(encoding="utf-8")
        self.assertIn("Requires=dsm-controller-service-topology.service", text)
        self.assertIn("dsm-dashboard-worker.service", text)
        self.assertIn("dsm-alert-engine.service", text)

    def test_retired_standalone_units_are_not_shipped(self):
        for name in (
            "dsm-monitor.service",
            "dsm-scheduler.service",
            "dsm-automation-worker.service",
        ):
            self.assertFalse((ROOT / "systemd" / name).exists(), name)

    def test_topology_reconciler_removes_retired_units(self):
        text = (ROOT / "systemd" / "controller-service-topology.sh").read_text(encoding="utf-8")
        for name in (
            "dsm-monitor.service",
            "dsm-scheduler.service",
            "dsm-automation-worker.service",
        ):
            self.assertIn(name, text)
        self.assertIn('systemctl disable --now "$unit"', text)

    def test_service_health_is_observational_and_reports_inactive_units(self):
        results = {
            "dsm-controller-service-topology.service": (0, "active\n"),
            "dsm-controller-log-reader.service": (0, "active\n"),
            "dsm-dashboard-worker.service": (3, "inactive\n"),
            "dsm-alert-engine.service": (0, "active\n"),
            "dsm-dashboard.service": (0, "active\n"),
        }

        def run(argv, **kwargs):
            code, out = results[argv[-1]]
            return subprocess.CompletedProcess(argv, code, stdout=out, stderr="")

        with mock.patch.object(controller_service_health, "_systemd_available", return_value=True), \
             mock.patch.object(controller_service_health.subprocess, "run", side_effect=run) as mocked:
            payload = controller_service_health.controller_service_health()

        self.assertTrue(payload["checked"])
        self.assertFalse(payload["ready"])
        self.assertEqual(payload["inactive"], ["dsm-dashboard-worker.service"])
        for call in mocked.call_args_list:
            self.assertEqual(call.args[0][:2], ["systemctl", "is-active"])

    def test_ci_without_systemd_does_not_fail_readiness(self):
        with mock.patch.object(controller_service_health, "_systemd_available", return_value=False), \
             mock.patch.object(controller_service_health.subprocess, "run") as mocked:
            payload = controller_service_health.controller_service_health()
        self.assertFalse(payload["checked"])
        self.assertTrue(payload["ready"])
        mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
