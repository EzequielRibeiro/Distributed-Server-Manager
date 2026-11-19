#!/usr/bin/env python3
"""Regression tests for customer-facing community DayZ mission display labels."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dashboard" / "customer_dayz_http.py"


def _display_names():
    """Execute the real pure formatter without booting the dashboard/database."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "_community_display_names")
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["_community_display_names"]


class FakeContent:
    def __init__(self, entries):
        self.entries = entries

    def list(self, *, instance_id, limit):
        return list(self.entries.values())

    def get(self, instance_id, content_id):
        return self.entries.get(content_id)


class DayZCommunityVariantLabelsTest(unittest.TestCase):
    def setUp(self):
        self.format = _display_names()
        self.id = "dayz-map:namalsk"
        self.store = FakeContent({
            self.id: {"content_id": self.id, "content_type": "map",
                      "desired_state": "installed",
                      "metadata": {"community_map": {"name": "Namalsk"}}},
        })

    def mission(self, mission_id, name="Namalsk", **extra):
        return {"id": mission_id, "name": name, "community": True,
                "content_id": self.id, "active": False, **extra}

    def test_namalsk_variants_named_even_when_agent_supplies_same_display_name(self):
        raw = {"current": "regular.namalsk", "current_name": "Namalsk",
               "missions": [
                   {**self.mission("regular.namalsk"), "active": True},
                   self.mission("hardcore.namalsk"),
               ]}
        result = self.format(self.store, "dayz-002", raw)
        self.assertEqual(
            {x["id"]: x["name"] for x in result["missions"]},
            {"regular.namalsk": "Namalsk — Regular",
             "hardcore.namalsk": "Namalsk — Hardcore"},
        )
        self.assertEqual(result["current_name"], "Namalsk — Regular")
        self.assertEqual(raw["missions"][0]["name"], "Namalsk")
        self.assertEqual([x["id"] for x in result["missions"]],
                         ["regular.namalsk", "hardcore.namalsk"])

    def test_legacy_id_based_labels_and_single_mission(self):
        both = [self.mission("regular.namalsk", "regular.namalsk"),
                self.mission("hardcore.namalsk", "hardcore.namalsk")]
        result = self.format(self.store, "dayz-002", {"missions": both})
        self.assertEqual([x["name"] for x in result["missions"]],
                         ["Namalsk — Regular", "Namalsk — Hardcore"])
        single = self.format(self.store, "dayz-002",
                             {"missions": [self.mission("regular.namalsk")]})
        self.assertEqual(single["missions"][0]["name"], "Namalsk")

    def test_existing_specific_name_and_other_map_unchanged(self):
        entries = [self.mission("regular.namalsk", "Custom Regular"),
                   self.mission("hardcore.namalsk", "Custom Hardcore"),
                   {"id": "dayzOffline.chernarusplus", "name": "Chernarus",
                    "official": True, "community": False}]
        result = self.format(self.store, "dayz-002", {"missions": entries})
        self.assertEqual([x["name"] for x in result["missions"]],
                         ["Custom Regular", "Custom Hardcore", "Chernarus"])

    def test_removed_map_is_not_exposed(self):
        self.store.entries[self.id]["desired_state"] = "absent"
        result = self.format(self.store, "dayz-002",
                             {"missions": [self.mission("regular.namalsk"),
                                           self.mission("hardcore.namalsk")]})
        self.assertEqual(result["missions"], [])


if __name__ == "__main__":
    unittest.main()
