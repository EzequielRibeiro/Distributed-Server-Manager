#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "installer" / "version_resolvers" / "neoforge_maven.sh"


class NeoForgeMavenRecommendedBuildTest(unittest.TestCase):
    def test_list_marks_only_latest_build_per_minecraft_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "maven-metadata.xml").write_text(
                """<metadata><versioning><versions>
<version>20.2.1</version><version>20.2.2</version>
<version>21.1.1</version><version>21.1.3</version>
</versions></versioning></metadata>""",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["NEOFORGE_MAVEN_BASE"] = base.as_uri()
            command = f"source {RESOLVER}; version_resolver_execute list x x x"
            result = subprocess.run(
                ["bash", "-lc", command], env=env, text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            by_mc = {}
            for item in payload["versions"]:
                by_mc.setdefault(item["version"], []).append(item)
            self.assertEqual(
                ["20.2.2"],
                [item["build"] for item in by_mc["1.20.2"] if item["recommended"]],
            )
            self.assertEqual(
                ["21.1.3"],
                [item["build"] for item in by_mc["1.21.1"] if item["recommended"]],
            )


if __name__ == "__main__":
    unittest.main()
