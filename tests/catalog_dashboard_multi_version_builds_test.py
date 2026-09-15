#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "dashboard" / "api" / "catalog.sh"


class CatalogDashboardMultiVersionBuildsTest(unittest.TestCase):
    def make_root(self, root: Path) -> Path:
        runtime_dir = root / "catalog" / "v2" / "games" / "minecraft" / "runtimes"
        resolver_dir = root / "installer" / "version_resolvers"
        runtime_dir.mkdir(parents=True)
        resolver_dir.mkdir(parents=True)
        (root / "installer" / "catalog.sh").write_text(
            "#!/usr/bin/env bash\nexit 2\n",
            encoding="utf-8",
        )
        (root / "installer" / "catalog_paths.sh").write_text(
            (ROOT / "installer" / "catalog_paths.sh").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        runtime = {
            "id": "minecraft.fake.multiversion",
            "game": "minecraft",
            "variant": "fake",
            "version": {
                "strategy": "dynamic",
                "resolver": "fake_multiversion",
            },
        }
        (runtime_dir / "fake-multiversion.json").write_text(
            json.dumps(runtime),
            encoding="utf-8",
        )
        marker = root / "resolve-called"
        resolver = resolver_dir / "fake_multiversion.sh"
        resolver.write_text(
            f'''#!/usr/bin/env bash
version_resolver_execute() {{
  local action="$1"
  case "$action" in
    list)
      printf '%s\\n' '{{"versions":[{{"tag":"release-x","minecraft_versions":["1.20.2","1.20.4","1.21.1"]}}]}}'
      ;;
    resolve)
      printf '%s\\n' called >> "{marker!s}"
      printf '%s\\n' '{{"error":"unexpected_resolve"}}'
      return 1
      ;;
    *)
      return 2
      ;;
  esac
}}
''',
            encoding="utf-8",
        )
        return marker

    def run_catalog(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, DSM_ROOT=str(root))
        return subprocess.run(
            [str(CATALOG), *args],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_versions_publish_every_minecraft_version_from_release(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.make_root(root)
            result = self.run_catalog(root, "versions", "minecraft.fake.multiversion")
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                ["1.20.2", "1.20.4", "1.21.1"],
                [item["value"] for item in payload],
            )

    def test_single_tag_build_is_reused_without_second_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            marker = self.make_root(root)
            result = self.run_catalog(
                root,
                "builds",
                "minecraft.fake.multiversion",
                "1.21.1",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(
                [{"value": "release-x", "label": "Build release-x", "recommended": True}],
                payload,
            )
            self.assertFalse(
                marker.exists(),
                "build discovery must not call resolve when the canonical list already has one compatible tag",
            )


if __name__ == "__main__":
    unittest.main()
