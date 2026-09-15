#!/usr/bin/env python3
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "dashboard" / "web" / "runtime-selector.js"


class CustomerRuntimeSelectorBuildResilienceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.javascript = SELECTOR.read_text(encoding="utf-8")

    def test_build_requests_are_generation_guarded(self):
        text = self.javascript
        self.assertIn("buildRequestGeneration: 0", text)
        self.assertIn("const generation = ++state.buildRequestGeneration", text)
        self.assertIn("generation === state.buildRequestGeneration", text)
        self.assertIn("state.runtime?.id === runtimeId", text)
        self.assertIn("state.version?.value === versionValue", text)
        self.assertGreaterEqual(
            text.count("if (!isCurrentRequest()) return;"),
            3,
            "success and error paths must ignore stale build responses",
        )

    def test_build_failure_leaves_recoverable_non_loading_state(self):
        text = self.javascript
        self.assertIn(
            'new Option("Não foi possível carregar builds — escolha outra versão", "")',
            text,
        )
        self.assertIn("state.build = null;", text)
        self.assertIn("updateSummary();", text)
        self.assertIn(
            "Não foi possível carregar as builds:",
            text,
        )

    def test_selection_changes_invalidate_inflight_build_requests(self):
        text = self.javascript
        for function_name in (
            "selectEdition",
            "selectDistribution",
            "selectVersion",
            "closeSelector",
        ):
            start = text.index(f"function {function_name}(")
            next_function = text.find("\n    function ", start + 1)
            next_async = text.find("\n    async function ", start + 1)
            candidates = [index for index in (next_function, next_async)  if index != -1]
            end = min(candidates) if candidates else len(text)
            block = text[start:end]
            self.assertIn(
                "state.buildRequestGeneration += 1;",
                block,
                f"{function_name} must invalidate an in-flight build request",
            )


if __name__ == "__main__":
    unittest.main()
