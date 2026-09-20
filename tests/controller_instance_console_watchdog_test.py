from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1] / "dashboard" / "web"
SOURCE_PATHS = {
    "controller": ROOT / "controller-instance-runtime-live.js",
    "customer": ROOT / "customer-instance-runtime-live.js",
}


class InstanceConsoleWatchdogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {
            name: path.read_text(encoding="utf-8")
            for name, path in SOURCE_PATHS.items()
        }

    def function_body(self, source: str, name: str) -> str:
        match = re.search(rf"function {re.escape(name)}\([^)]*\)\{{([^\n]*)\}}", source)
        self.assertIsNotNone(match, f"missing function {name}")
        return match.group(1)

    def test_open_keepalive_does_not_count_as_lifecycle_progress(self):
        for surface, source in self.sources.items():
            with self.subTest(surface=surface):
                ensure = self.function_body(source, "ensureConsoleTransport")
                onopen = ensure.split("stream.onopen=()=>{", 1)[1].split("};stream.addEventListener", 1)[0]
                self.assertNotIn("markConsoleLifecycleProgress", onopen)
                self.assertIn('stream.addEventListener("console-snapshot"', ensure)
                self.assertIn('stream.addEventListener("console-line"', ensure)
                self.assertGreaterEqual(ensure.count("markConsoleStreamProgress()"), 2)
                stream_progress = self.function_body(source, "markConsoleStreamProgress")
                self.assertIn("markConsoleLifecycleProgress()", stream_progress)

    def test_open_but_silent_sse_uses_safety_poll(self):
        for surface, source in self.sources.items():
            with self.subTest(surface=surface):
                self.assertIn("CONSOLE_SAFETY_POLL_MS=3000", source)
                self.assertIn("CONSOLE_SSE_STALE_MS=6000", source)
                safety = self.function_body(source, "startConsoleSafetyPoll")
                self.assertIn("setInterval", safety)
                self.assertIn("Date.now()-lastConsoleStreamDataAt>=CONSOLE_SSE_STALE_MS", safety)
                self.assertIn("refreshConsole()", safety)
                ensure = self.function_body(source, "ensureConsoleTransport")
                self.assertIn("startConsoleSafetyPoll()", ensure)
                stop = self.function_body(source, "stopConsoleStream")
                self.assertIn("stopConsoleSafetyPoll()", stop)
                self.assertIn("lastConsoleStreamDataAt=0", stop)

    def test_stale_lifecycle_stream_reconnects_and_refreshes_snapshot(self):
        for surface, source in self.sources.items():
            with self.subTest(surface=surface):
                recover = self.function_body(source, "recoverStaleConsoleStream")
                self.assertIn("stale.close()", recover)
                self.assertIn("consoleStream=null", recover)
                self.assertIn("refreshConsole()", recover)
                self.assertIn("ensureConsoleTransport()", recover)

    def test_watchdog_is_scoped_to_start_and_restart(self):
        for surface, source in self.sources.items():
            with self.subTest(surface=surface):
                self.assertIn('consoleLifecycleActions=new Set(["start","restart"])', source)
                arm = self.function_body(source, "armConsoleLifecycleWatchdog")
                self.assertIn("consoleLifecycleActions.has(action)", arm)
                self.assertIn("consoleViewActive()", arm)
                self.assertIn('permissions().has("console.read")', arm)

    def test_repeated_lifecycle_action_replaces_timer_and_cleanup_stops_it(self):
        for surface, source in self.sources.items():
            with self.subTest(surface=surface):
                arm = self.function_body(source, "armConsoleLifecycleWatchdog")
                self.assertTrue(arm.startswith("stopConsoleLifecycleWatchdog();"))
                self.assertIn("setTimeout(recoverStaleConsoleStream,CONSOLE_LIFECYCLE_WATCHDOG_MS)", arm)
                stop = self.function_body(source, "stopConsoleStream")
                self.assertTrue(stop.startswith("stopConsoleLifecycleWatchdog();"))
                self.assertIn('window.addEventListener("beforeunload",stopConsoleStream,{once:true})', source)

    def test_multiline_copy_preserves_console_line_breaks(self):
        for surface, source in self.sources.items():
            with self.subTest(surface=surface):
                copy_body = self.function_body(source, "copyConsoleSelection")
                self.assertIn('querySelectorAll(".console-line")', copy_body)
                self.assertIn('lines.length<2', copy_body)
                self.assertIn('lines.map(node=>node.textContent).join("\\n")', copy_body)
                self.assertIn('event.clipboardData.setData("text/plain"', copy_body)
                self.assertIn('event.preventDefault()', copy_body)
                self.assertIn(
                    '$("console-output")?.addEventListener("copy",copyConsoleSelection)',
                    source,
                )

    def test_successful_lifecycle_request_arms_watchdog_on_both_surfaces(self):
        for surface, source in self.sources.items():
            with self.subTest(surface=surface):
                self.assertIn("if(response.ok)armConsoleLifecycleWatchdog(action)", source)
                self.assertIn("CONSOLE_LIFECYCLE_WATCHDOG_MS=8000", source)


if __name__ == "__main__":
    unittest.main()
