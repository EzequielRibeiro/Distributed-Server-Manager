from pathlib import Path
import re
import unittest


SOURCE_PATH = Path(__file__).resolve().parents[1] / "dashboard" / "web" / "controller-instance-runtime-live.js"


class ControllerInstanceConsoleWatchdogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE_PATH.read_text(encoding="utf-8")

    def function_body(self, name: str) -> str:
        match = re.search(rf"function {re.escape(name)}\([^)]*\)\{{([^\n]*)\}}", self.source)
        self.assertIsNotNone(match, f"missing function {name}")
        return match.group(1)

    def test_open_keepalive_does_not_count_as_lifecycle_progress(self):
        ensure = self.function_body("ensureConsoleTransport")
        onopen = ensure.split("stream.onopen=()=>{", 1)[1].split("};stream.addEventListener", 1)[0]
        self.assertNotIn("markConsoleLifecycleProgress", onopen)
        self.assertIn('stream.addEventListener("console-snapshot"', ensure)
        self.assertIn('stream.addEventListener("console-line"', ensure)
        self.assertGreaterEqual(ensure.count("markConsoleLifecycleProgress()"), 2)

    def test_stale_lifecycle_stream_reconnects_and_refreshes_snapshot(self):
        recover = self.function_body("recoverStaleConsoleStream")
        self.assertIn("stale.close()", recover)
        self.assertIn("consoleStream=null", recover)
        self.assertIn("refreshConsole()", recover)
        self.assertIn("ensureConsoleTransport()", recover)

    def test_watchdog_is_scoped_to_start_and_restart(self):
        self.assertIn('consoleLifecycleActions=new Set(["start","restart"])', self.source)
        arm = self.function_body("armConsoleLifecycleWatchdog")
        self.assertIn("consoleLifecycleActions.has(action)", arm)
        self.assertIn("consoleViewActive()", arm)
        self.assertIn('permissions().has("console.read")', arm)

    def test_repeated_lifecycle_action_replaces_timer_and_cleanup_stops_it(self):
        arm = self.function_body("armConsoleLifecycleWatchdog")
        self.assertTrue(arm.startswith("stopConsoleLifecycleWatchdog();"))
        self.assertIn("setTimeout(recoverStaleConsoleStream,CONSOLE_LIFECYCLE_WATCHDOG_MS)", arm)
        stop = self.function_body("stopConsoleStream")
        self.assertTrue(stop.startswith("stopConsoleLifecycleWatchdog();"))
        self.assertIn('window.addEventListener("beforeunload",stopConsoleStream,{once:true})', self.source)


if __name__ == "__main__":
    unittest.main()
