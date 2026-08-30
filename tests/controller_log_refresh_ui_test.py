from pathlib import Path
import unittest


OBSERVABILITY_JS = Path("dashboard/web/observability.js")


class ControllerLogRefreshUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = OBSERVABILITY_JS.read_text(encoding="utf-8")
        start = cls.source.index("async function loadLogs()")
        end = cls.source.index("async function refresh()", start)
        cls.load_logs = cls.source[start:end]

    def test_refresh_builds_off_dom_before_atomic_swap(self):
        self.assertIn("document.createDocumentFragment()", self.load_logs)
        self.assertIn("t.replaceChildren(fragment)", self.load_logs)
        self.assertNotIn("t.replaceChildren();", self.load_logs)
        self.assertLess(
            self.load_logs.index("document.createDocumentFragment()"),
            self.load_logs.index("t.replaceChildren(fragment)"),
        )

    def test_identical_payload_does_not_mutate_log_dom(self):
        self.assertIn("logSignature(logs,message)", self.load_logs)
        self.assertIn("if(t.dataset.logSignature===signature)return", self.load_logs)
        self.assertIn("t.dataset.logSignature=signature", self.load_logs)
        self.assertLess(
            self.load_logs.index("if(t.dataset.logSignature===signature)return"),
            self.load_logs.index("t.replaceChildren(fragment)"),
        )

    def test_periodic_refresh_remains_enabled(self):
        self.assertIn("setInterval(refresh,30000)", self.source)


if __name__ == "__main__":
    unittest.main()
