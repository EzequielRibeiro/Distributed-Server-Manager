from pathlib import Path
import unittest


OBSERVABILITY_JS = Path("dashboard/web/observability.js")
OBSERVABILITY_CSS = Path("dashboard/web/observability.css")
CONTROLLER_LOGS_HTML = Path("dashboard/web/controller-logs.html")


class ControllerLogRefreshUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = OBSERVABILITY_JS.read_text(encoding="utf-8")
        cls.css = OBSERVABILITY_CSS.read_text(encoding="utf-8")
        cls.html = CONTROLLER_LOGS_HTML.read_text(encoding="utf-8")
        start = cls.source.index("async function performLogLoad()")
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
        self.assertIn("if(t.dataset.logSignature===signature)return true", self.load_logs)
        self.assertIn("t.dataset.logSignature=signature", self.load_logs)
        self.assertLess(
            self.load_logs.index("if(t.dataset.logSignature===signature)return true"),
            self.load_logs.index("t.replaceChildren(fragment)"),
        )

    def test_manual_refresh_has_loading_and_completion_feedback(self):
        self.assertIn('setLogsRefreshState("loading")', self.source)
        self.assertIn('setLogsRefreshState(success?"success":"error")', self.source)
        self.assertIn('button.textContent="Atualizando…"', self.source)
        self.assertIn('button.textContent="Atualizado ✓"', self.source)
        self.assertIn('button.textContent="Falha ao atualizar"', self.source)
        self.assertIn('button.setAttribute("aria-busy",loading?"true":"false")', self.source)
        self.assertIn('button.disabled=loading', self.source)
        self.assertIn('()=>loadLogs({interactive:true})', self.source)

    def test_loading_state_has_spinner_animation(self):
        self.assertIn("#btn-refresh-logs.is-loading::before", self.css)
        self.assertIn("animation:cap-log-refresh-spin", self.css)
        self.assertIn("@keyframes cap-log-refresh-spin", self.css)

    def test_log_page_exposes_accessible_feedback_and_cache_bust(self):
        self.assertIn('id="btn-refresh-logs"', self.html)
        self.assertIn('aria-live="polite" aria-busy="false"', self.html)
        self.assertIn('/observability.css?v=6', self.html)
        self.assertIn('/observability.js?v=6', self.html)

    def test_periodic_refresh_remains_enabled(self):
        self.assertIn("setInterval(refresh,30000)", self.source)


if __name__ == "__main__":
    unittest.main()
