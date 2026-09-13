#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_CATALOG = ROOT / "dashboard" / "api" / "catalog.sh"
CATALOG_PATHS = ROOT / "installer" / "catalog_paths.sh"


class CatalogDashboardResolverSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "dashboard" / "api").mkdir(parents=True)
        (self.root / "installer" / "version_resolvers").mkdir(parents=True)
        (self.root / "catalog" / "v2" / "games" / "minecraft" / "runtimes").mkdir(parents=True)
        shutil.copy2(DASHBOARD_CATALOG, self.root / "dashboard" / "api" / "catalog.sh")
        shutil.copy2(CATALOG_PATHS, self.root / "installer" / "catalog_paths.sh")
        (self.root / "installer" / "catalog.sh").write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
        (self.root / "installer" / "provider_loader.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_runtime(self, resolver: str) -> str:
        runtime_id = "minecraft.java.fake"
        payload = {
            "schema_version": 2,
            "kind": "RuntimeDefinition",
            "id": runtime_id,
            "game": "minecraft",
            "edition": "java",
            "variant": "fake",
            "version": {"strategy": "dynamic", "resolver": resolver},
        }
        path = self.root / "catalog" / "v2" / "games" / "minecraft" / "runtimes" / "fake.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return runtime_id

    def write_resolver(self, name: str, body: str) -> None:
        path = self.root / "installer" / "version_resolvers" / f"{name}.sh"
        path.write_text(body, encoding="utf-8")

    def run_catalog(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.root / "dashboard" / "api" / "catalog.sh"), *args],
            cwd=self.root,
            env={"PATH": str(Path(shutil.which("bash") or "/bin/bash").parent) + ":/usr/bin:/bin", "DSM_ROOT": str(self.root)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_dynamic_versions_and_builds_use_canonical_resolver(self) -> None:
        runtime_id = self.write_runtime("fake_api")
        self.write_resolver(
            "fake_api",
            r'''#!/usr/bin/env bash
version_resolver_execute() {
    local action="$1" selector="${4:-}"
    case "$action" in
        list) printf '%s\n' '{"versions":[{"version":"1.21.1","build":"42"},{"version":"1.21.1","build":"41"},{"version":"1.20.6","build":"9"}]}' ;;
        resolve) printf '{"version":"%s","build":"42"}\n' "$selector" ;;
        *) return 2 ;;
    esac
}
''',
        )

        versions = self.run_catalog("versions", runtime_id)
        self.assertEqual(0, versions.returncode, versions.stderr)
        version_payload = json.loads(versions.stdout)
        self.assertEqual(["1.21.1", "1.20.6"], [item["value"] for item in version_payload])

        builds = self.run_catalog("builds", runtime_id, "1.21.1")
        self.assertEqual(0, builds.returncode, builds.stderr)
        build_payload = json.loads(builds.stdout)
        self.assertEqual(["42", "41"], [item["value"] for item in build_payload])
        self.assertEqual(["42"], [item["value"] for item in build_payload if item["recommended"]])

    def test_maven_full_build_marks_suffix_as_recommended(self) -> None:
        runtime_id = self.write_runtime("fake_maven")
        self.write_resolver(
            "fake_maven",
            r'''#!/usr/bin/env bash
version_resolver_execute() {
    local action="$1" selector="${4:-}"
    case "$action" in
        list) printf '%s\n' '{"versions":[{"version":"1.21.1","build":"52.1.15"},{"version":"1.21.1","build":"52.1.16"}]}' ;;
        resolve) printf '{"version":"%s","build":"1.21.1-52.1.16"}\n' "$selector" ;;
        *) return 2 ;;
    esac
}
''',
        )

        builds = self.run_catalog("builds", runtime_id, "1.21.1")
        self.assertEqual(0, builds.returncode, builds.stderr)
        payload = json.loads(builds.stdout)
        self.assertEqual(["52.1.16"], [item["value"] for item in payload if item["recommended"]])

    def test_missing_resolver_returns_json_error(self) -> None:
        runtime_id = self.write_runtime("does_not_exist")
        completed = self.run_catalog("versions", runtime_id)
        self.assertEqual(2, completed.returncode)
        payload = json.loads(completed.stdout)
        self.assertEqual("unsupported_version_resolver", payload["error"])


if __name__ == "__main__":
    unittest.main()
