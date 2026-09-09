#!/usr/bin/env python3

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class InstanceRuntimeStatusUiTest(unittest.TestCase):
    def test_unknown_runtime_state_does_not_collapse_to_offline(self):
        script = (WEB / "servers.js").read_text(encoding="utf-8")

        self.assertIn(
            'if(["offline","stopped"].includes(r))return"offline";',
            script,
        )
        self.assertIn('return"unknown";', script)
        self.assertIn('return"Desconhecido";', script)

    def test_detail_failure_preserves_runtime_list_projection(self):
        script = (WEB / "servers.js").read_text(encoding="utf-8")

        for token in (
            "const summaryStatus=normalizeStatus(summary);",
            "const resourceStatus=normalizeStatus(resource);",
            'const status=summaryStatus==="unknown"?resourceStatus:summaryStatus;',
            "Runtime detail unavailable; preserving list projection",
        ):
            self.assertIn(token, script)

    def test_unknown_state_has_distinct_filter_and_presentation(self):
        page = (WEB / "servers.html").read_text(encoding="utf-8")
        styles = (WEB / "servers.css").read_text(encoding="utf-8")

        self.assertIn('data-filter="unknown"', page)
        self.assertIn('>Desconhecido</button>', page)
        self.assertIn('data-state="unknown"', styles)
        self.assertIn('.cap-state.unknown', styles)

    def test_offline_counter_only_counts_confirmed_offline_state(self):
        script = (WEB / "servers.js").read_text(encoding="utf-8")
        page = (WEB / "servers.html").read_text(encoding="utf-8")

        self.assertIn(
            'state.instances.filter(i=>i.status==="offline").length',
            script,
        )
        self.assertIn("paradas confirmadas", page)


if __name__ == "__main__":
    unittest.main()
