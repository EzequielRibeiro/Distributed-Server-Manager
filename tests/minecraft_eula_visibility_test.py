#!/usr/bin/env python3
"""Minecraft EULA should appear and gate creation for Java only."""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"


class MinecraftEulaVisibilityTest(unittest.TestCase):
    def test_game_edition_predicate_executes_in_real_selector_script(self):
        script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const window = {};
const document = {addEventListener() {}};
const context = {window, document};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const required = window.CapivaraRuntimeSelector.requiresMinecraftJavaEula;
assert.equal(typeof required, 'function');
const cases = [
  ['dayz','default',false],
  ['rust','java',false],
  ['palworld','java',false],
  ['minecraft','bedrock',false],
  ['minecraft','default',false],
  ['minecraft','java',true],
  ['MINECRAFT','JAVA',true],
];
for (const [game, edition, expected] of cases) {
  assert.equal(required(game, edition), expected, game + '/' + edition);
}
"""
        result = subprocess.run(
            ["node", "-e", script, str(WEB / "runtime-selector.js")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_visibility_uses_actual_selection_not_stale_text(self):
        selector = (WEB / "runtime-selector.js").read_text()
        wizard = (WEB / "create-server-wizard.js").read_text()
        self.assertIn(
            "const minecraftJavaEula = requiresMinecraftJavaEula(state.game, state.edition);",
            selector,
        )
        self.assertIn(
            "el.minecraftNotice.hidden = !complete || !minecraftJavaEula;",
            selector,
        )
        self.assertIn("el.minecraftEula.checked = false;", selector)
        self.assertIn(
            "selector?.requiresMinecraftJavaEula?.(selected?.game,selected?.edition)",
            wizard,
        )

    def test_hidden_attribute_wins_over_author_display_grid(self):
        css = (WEB / "create-server-wizard.css").read_text()
        self.assertRegex(
            css,
            re.compile(
                r"\.runtime-create-panel\[hidden\],\s*"
                r"\.runtime-create-panel \[hidden\]\s*\{\s*"
                r"display:\s*none\s*!important\s*;",
                re.S,
            ),
        )
        self.assertIn("display: grid;", css)

    def test_markup_is_hidden_and_cache_version_changes(self):
        html = (WEB / "customer.html").read_text()
        self.assertIn('id="minecraft-runtime-notice" class="runtime-notice" hidden', html)
        for marker in (
            '/create-server-wizard.css?v=8',
            '/runtime-selector.js?v=13',
            '/create-server-wizard.js?v=5',
        ):
            self.assertIn(marker, html)


if __name__ == "__main__":
    unittest.main()
