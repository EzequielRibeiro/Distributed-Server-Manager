#!/usr/bin/env python3
"""Deterministic regression tests for the read-only historical DayZ PBO comparator."""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "dayz_pbo_log_compare.py"
spec = importlib.util.spec_from_file_location("dayz_pbo_log_compare", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def line(folder: str, name: str) -> str:
    return (
        "17:58:29 ENGINE       : PBO Load "
        f"'/tmp/sandbox/serverfiles/{folder}/addons\\{name}'"
    )


class DayZPboLogCompareTest(unittest.TestCase):
    def test_categorizes_base_and_known_dlcs(self):
        log = "\n".join([
            line("nasdara", "worlds_nasdara_ce"),
            line("sakhal", "worlds_sakhal"),
            line("addons", "base_script"),
            "17:58:30 ANIMATION (E): Can't load nasdara/Anims/cfg/skeletons.anim.xml",
        ])
        data = module.inventory(log)
        self.assertEqual((data["base"], data["nasdara"], data["sakhal"], data["total"]),
                         (1, 1, 1, 3))

    def test_comparison_reports_delta_but_never_causality(self):
        base = line("addons", "base_script")
        before = base
        after = "\n".join([base, line("nasdara", "worlds_nasdara_ce"),
                           line("sakhal", "worlds_sakhal")])
        report = module.compare(before, after)
        self.assertTrue(report["base_count_stable"])
        self.assertEqual(report["dlc_delta"], {"nasdara": 1, "sakhal": 1})
        self.assertFalse(report["causality_established"])

    def test_compares_actual_package_names_not_only_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dlc in ("nasdara", "sakhal"):
                (root / dlc / "addons").mkdir(parents=True)
            (root / "nasdara/addons/a.pbo").write_bytes(b"x")
            (root / "nasdara/addons/b.pbo").write_bytes(b"x")
            (root / "sakhal/addons/c.ebo").write_bytes(b"x")
            report = module.compare_installed("\n".join([
                line("nasdara", "a"), line("nasdara", "unexpected"),
                line("sakhal", "c")]), root)
            self.assertEqual(report["nasdara"]["missing_from_engine"], ["b"])
            self.assertEqual(report["nasdara"]["unexpected_in_engine"], ["unexpected"])
            self.assertEqual(report["sakhal"]["missing_from_engine"], [])
            self.assertEqual(report["sakhal"]["unexpected_in_engine"], [])

    def test_does_not_count_non_engine_or_duplicate_packages_as_unique(self):
        match = line("nasdara", "foo")
        log = "\n".join([match, match, "RPT mentions PBO Load nasdara", line("other", "foo")])
        data = module.inventory(log)
        self.assertEqual(data["nasdara"], 2)
        self.assertEqual(data["unique_packages"]["nasdara"], 1)
        self.assertEqual(data["other"], 1)


if __name__ == "__main__":
    unittest.main()
