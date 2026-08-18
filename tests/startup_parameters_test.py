#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


from core.runtime.startup_parameters import build_effective_argv


class StartupParametersTest(unittest.TestCase):
    def test_effective_argv(self):
        definition = {
            "process": {
                "args": ["-config=serverDZ.cfg"],
                "parameters": [
                    {
                        "id": "profiles",
                        "argument": "-profiles={value}",
                        "default": "profiles",
                    },
                    {
                        "id": "adminlog",
                        "argument": "-adminlog",
                        "kind": "flag",
                        "default": True,
                    },
                ],
            }
        }

        argv = build_effective_argv(definition)

        self.assertEqual(
            argv,
            [
                "-config=serverDZ.cfg",
                "-profiles=profiles",
                "-adminlog",
            ],
        )


if __name__ == "__main__":
    unittest.main()
