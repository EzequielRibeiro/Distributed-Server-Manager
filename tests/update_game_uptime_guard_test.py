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
        "Requisite": "", "Wants": "network.target", "Upholds": "",
        "Conflicts": "", "Triggers": "", "StopPropagatedFrom": "",
        "PropagatesStopTo": "", "BoundBy": "", "ConsistsOf": "",
        "RequiredBy": "", "WantedBy": "multi-user.target",
        "UpheldBy": "", "ConflictedBy": "", "TriggeredBy": "",
        "ExecCondition": "", "ExecStartPre": "", "ExecStartPost": "",
        "ExecStop": "", "ExecStopPost": "", "ExecReload": "",
        "WorkingDirectory": "/var/lib/capivara-instances/example",
        "EnvironmentFiles": "", "RootDirectory": "", "RootImage": "",
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

    def test_reverse_dependency_via_worker_blocks_no_drain(self):
        # Normal forward links are absent; a reverse control-plane relation
        # must still be considered unsafe for a selective daemon restart.
        for prop in ("BoundBy", "ConsistsOf", "RequiredBy", "WantedBy",
                     "UpheldBy", "ConflictedBy", "TriggeredBy"):
            with self.subTest(prop=prop), self.assertRaisesRegex(
                    guard.GateError, "control-plane dependency"):
                guard.inspect("capivara-instance-example.service",
                              fake(example(**{prop: "dsm-dashboard-worker.service"})))

    def test_conflicting_controller_unit_blocks_preflight(self):
        with self.assertRaisesRegex(guard.GateError, "Conflicts"):
            guard.inspect("capivara-instance-example.service",
                          fake(example(Conflicts="dsm-dashboard.service")))

    def test_benign_system_dependencies_do_not_block(self):
        verified = guard.inspect("capivara-instance-example.service",
                                 fake(example(
                                     Wants="network.target sysinit.target",
                                     WantedBy="multi-user.target",
                                     RequiredBy="network-online.target")))
        self.assertEqual(verified["main_pid"], 2031)
        self.assertEqual(len(verified["unit_config_sha256"]), 64)

    def test_reverse_link_change_invalidates_original_witness(self):
        first = guard.inspect("capivara-instance-example.service",
                              fake(example()))
        with self.assertRaisesRegex(guard.GateError, "changed"):
            guard.verify_unchanged(first,
                fake(example(WantedBy="multi-user.target network-online.target")))

    def test_missing_reverse_dependency_property_fails_closed(self):
        raw = "\n".join(line for line in example().splitlines()
                        if not line.startswith("ConflictedBy="))
        with self.assertRaisesRegex(guard.GateError, "incomplete"):
            guard.inspect("capivara-instance-example.service", fake(raw))

    def test_systemd_guard_is_strictly_read_only(self):
        calls = []
        def recorder(*args):
            calls.append(args)
            return example()
        guard.inspect("capivara-instance-example.service", recorder)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ("systemctl", "show"))
        self.assertIn("--property=ConflictedBy", calls[0])
        self.assertIn("--property=UpheldBy", calls[0])

    def test_replaceable_lifecycle_hooks_fail_closed(self):
        for prop in guard.LIFECYCLE_PROPERTIES:
            with self.subTest(prop=prop), self.assertRaisesRegex(guard.GateError, prop):
                guard.inspect("capivara-instance-example.service", fake(example(
                    **{prop: "{ path=/usr/bin/python3 ; argv[]=/usr/bin/python3 /opt/dsm/agents/linux/runtime/hook.py ; }"})))

    def test_replaceable_unit_path_directives_fail_closed(self):
        for prop in guard.PATH_PROPERTIES:
            with self.subTest(prop=prop), self.assertRaisesRegex(guard.GateError, prop):
                guard.inspect("capivara-instance-example.service", fake(example(
                    **{prop: "/opt/dsm/agents/linux/runtime/replaceable"})))

    def test_unit_hook_change_rejected_even_with_same_pid(self):
        original = guard.inspect("capivara-instance-example.service", fake(example()))
        with self.assertRaisesRegex(guard.GateError, "changed"):
            guard.verify_unchanged(original, fake(example(ExecStop=
                "{ path=/usr/bin/true ; argv[]=/usr/bin/true ; }")))

    def test_safe_auxiliary_hook_included_in_digest(self):
        value = guard.inspect("capivara-instance-example.service", fake(example(
            ExecStartPre="{ path=/usr/bin/true ; argv[]=/usr/bin/true ; }")))
        self.assertEqual(len(value["unit_config_sha256"]), 64)
        self.assertNotIn("ExecStartPre", value)

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
