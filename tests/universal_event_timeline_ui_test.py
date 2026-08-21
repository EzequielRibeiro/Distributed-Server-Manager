import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UniversalEventTimelineUiTest(unittest.TestCase):
    def test_timeline_ui_consumes_universal_endpoint(self):
        script = (ROOT / "dashboard/web/js/timeline-ui.js").read_text(encoding="utf-8")

        self.assertIn('const TIMELINE_ENDPOINT = "/api/events/timeline"', script)
        self.assertIn("window.loadTimeline = loadTimeline", script)
        self.assertIn("window.setTimelineFilter = setTimelineFilter", script)
        self.assertNotIn("timeline?limit=", script)
        self.assertNotIn(".innerHTML =", script)

    def test_timeline_ui_redacts_sensitive_payload_keys(self):
        script = (ROOT / "dashboard/web/js/timeline-ui.js").read_text(encoding="utf-8")

        self.assertIn("SENSITIVE_KEY", script)
        for marker in ("secret", "token", "password", "credential", "authorization", "cookie"):
            self.assertIn(marker, script)

    def test_phase21_wrapper_registers_and_loads_timeline_ui(self):
        wrapper = (ROOT / "dashboard/server_part14.py").read_text(encoding="utf-8")

        self.assertIn('TIMELINE_UI_PATH = "/js/timeline-ui.js"', wrapper)
        self.assertIn("legacy.STATIC_FILES[TIMELINE_UI_PATH]", wrapper)
        self.assertIn("TIMELINE_SCRIPT_TAG", wrapper)
        self.assertIn("_serve_phase21_index", wrapper)
        self.assertIn("import server_part13 as integration", wrapper)
        self.assertNotIn("import server as", wrapper)

    def test_visible_filters_are_universal_domains(self):
        script = (ROOT / "dashboard/web/js/timeline-ui.js").read_text(encoding="utf-8")

        for label in ("Infraestrutura", "Instâncias", "Conteúdo", "Segurança"):
            self.assertIn(label, script)
        for legacy_filter in ('["player",', '["combat",', '["mods",', '["audit",'):
            self.assertNotIn(legacy_filter, script)


if __name__ == "__main__":
    unittest.main()
