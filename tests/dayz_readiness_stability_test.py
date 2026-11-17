"""Regression tests for post-update transient DayZ start."""
import ast
import pathlib
import types
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / "agents/linux/runtime/server_update_agent.py"
TREE = ast.parse(SOURCE.read_text())
FUNCTION = next(x for x in TREE.body if isinstance(x, ast.FunctionDef) and x.name == "_restart_and_validate")

class Clock:
    def __init__(self):
        self.now = 0.0
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds

class ReadinessTests(unittest.TestCase):
    def run_case(self, fail_at=None):
        clock = Clock()
        starts = []
        def lifecycle(config, name, action):
            starts.append((name, action))
        def doctor(config, name):
            return {"ready": fail_at is None or clock.now < fail_at}
        def status(config, name):
            return {"observed_state": "running" if fail_at is None or clock.now < fail_at else "failed"}
        ns = {"time": clock, "instance_runtime": types.SimpleNamespace(lifecycle=lifecycle,doctor=doctor,status=status),"Any":object}
        module=ast.Module(body=[FUNCTION],type_ignores=[])
        exec(compile(module,str(SOURCE),"exec"),ns)
        return ns["_restart_and_validate"]({},["test-dayz"]), clock.now, starts
    def test_running_continuously_passes(self):
        (restarted,failures),duration,starts=self.run_case()
        self.assertEqual((restarted,failures),(["test-dayz"],[]))
        self.assertGreaterEqual(duration,15)
    def test_transient_running_fails(self):
        (restarted,failures),duration,starts=self.run_case(fail_at=10)
        self.assertEqual((restarted,failures),(["test-dayz"],["test-dayz"]))
        self.assertGreaterEqual(duration,30)

if __name__ == "__main__":
    unittest.main()
