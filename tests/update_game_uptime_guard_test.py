"""Systemd game process preservation gate: isolated fixtures."""
import importlib.machinery
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader(
    "game_uptime_guard", str(ROOT/"update-manager/game-uptime-guard.py"))
spec = importlib.util.spec_from_loader(loader.name, loader)
guard = importlib.util.module_from_spec(spec)
loader.exec_module(guard)


def example(**changes):
    values = {
        "ActiveState": "active",
        "MainPID": "2031",
        "ExecMainStartTimestampMonotonic": "123456000",
        "ExecStart": "{ path=/usr/bin/java ; argv[]=/usr/bin/java -jar server.jar ; }",
        "FragmentPath": "/etc/systemd/system/capivara-instance-example.service",
        "PartOf": "", "BindsTo": "", "Requires": "sysinit.target",
        "Requisite": "", "StopPropagatedFrom": "", "PropagatesStopTo": "",
    }
    values.update(changes)
    return "\n".join(k + "=" + v for k, v in values.items())


def fake(raw):
    return lambda *args: raw


class UptimeGuardTests(unittest.TestCase):
    def test_snapshot_and_stable_pid(self):
        first=guard.inspect("capivara-instance-example.service", fake(example()))
        current=guard.verify_unchanged(first, fake(example()))
        self.assertEqual(current["main_pid"],2031)

    def test_process_restarted_fails(self):
        prior=guard.inspect("capivara-instance-example.service", fake(example()))
        with self.assertRaisesRegex(guard.GateError, "changed"):
            guard.verify_unchanged(prior,fake(example(MainPID="2042")))

    def test_same_pid_different_start_fails(self):
        prior=guard.inspect("capivara-instance-example.service", fake(example()))
        with self.assertRaisesRegex(guard.GateError, "changed"):
            guard.verify_unchanged(
                prior,fake(example(ExecMainStartTimestampMonotonic="123456001")))

    def test_dashboard_dependency_fails(self):
        for prop in guard.DEPENDENCY_PROPERTIES:
            with self.subTest(prop=prop), self.assertRaises(guard.GateError):
                guard.inspect("capivara-instance-example.service",
                              fake(example(**{prop:"dsm-dashboard-worker.service"})))

    def test_python_console_supervisor_rejected(self):
        with self.assertRaisesRegex(guard.GateError, "replaceable"):
            guard.inspect("capivara-instance-example.service",
                          fake(example(ExecStart="{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /opt/dsm/agents/linux/runtime/console_supervisor.py ; }")))

    def test_missing_fields_fail_closed(self):
        with self.assertRaisesRegex(guard.GateError, "incomplete"):
            guard.inspect("capivara-instance-example.service",fake("ActiveState=active\nMainPID=123"))

    def test_inactive_or_untrusted_location_rejected(self):
        for payload in (example(ActiveState="inactive"),
                        example(FragmentPath="/tmp/forged.service")):
            with self.assertRaises(guard.GateError):
                guard.inspect("capivara-instance-example.service",fake(payload))

    def test_unknown_unit_rejected(self):
        with self.assertRaises(guard.GateError):
            guard.inspect("dsm-dashboard.service",fake(example()))


if __name__ == "__main__":
    unittest.main()
