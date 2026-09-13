#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "catalog" / "v2" / "games"
RESOLVER_ROOT = ROOT / "installer" / "version_resolvers"
DASHBOARD_CATALOG = ROOT / "dashboard" / "api" / "catalog.sh"


class CatalogDashboardResolverParityTest(unittest.TestCase):
    def dynamic_runtimes(self) -> list[tuple[Path, dict]]:
        result: list[tuple[Path, dict]] = []
        for path in sorted(RUNTIME_ROOT.glob("*/runtimes/*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            version = payload.get("version") if isinstance(payload, dict) else None
            if isinstance(version, dict) and version.get("strategy") == "dynamic":
                result.append((path, payload))
        return result

    def test_every_dynamic_runtime_has_a_canonical_resolver(self) -> None:
        dynamic = self.dynamic_runtimes()
        self.assertTrue(dynamic, "expected at least one dynamic RuntimeDefinition")
        missing: list[str] = []
        for path, runtime in dynamic:
            resolver = str(runtime["version"].get("resolver") or "").strip()
            if not resolver:
                missing.append(f"{path.relative_to(ROOT)}: missing version.resolver")
                continue
            resolver_file = RESOLVER_ROOT / f"{resolver}.sh"
            if not resolver_file.is_file():
                missing.append(
                    f"{path.relative_to(ROOT)}: resolver {resolver!r} has no "
                    f"{resolver_file.relative_to(ROOT)}"
                )
        self.assertEqual([], missing, "\n".join(missing))

    def test_every_published_dynamic_resolver_supports_list_and_resolve(self) -> None:
        resolvers = {
            str(runtime["version"].get("resolver") or "").strip()
            for _path, runtime in self.dynamic_runtimes()
        }
        resolvers.discard("")
        invalid: list[str] = []
        for resolver in sorted(resolvers):
            path = RESOLVER_ROOT / f"{resolver}.sh"
            text = path.read_text(encoding="utf-8")
            for required in ("version_resolver_execute", "list)", "resolve)"):
                if required not in text:
                    invalid.append(
                        f"{path.relative_to(ROOT)}: missing canonical action {required!r}"
                    )
        self.assertEqual([], invalid, "\n".join(invalid))

    def test_dashboard_uses_canonical_resolver_bridge(self) -> None:
        text = DASHBOARD_CATALOG.read_text(encoding="utf-8")
        for token in (
            'RESOLVER_ROOT="${DSM_ROOT}/installer/version_resolvers"',
            'source "${RESOLVER_FILE}"',
            "version_resolver_execute",
            "canonical_resolver_list",
            "canonical_resolver_call",
        ):
            self.assertIn(token, text)
        self.assertNotIn('case "${RESOLVER}" in', text)

    def test_dashboard_catalog_shell_is_syntactically_valid(self) -> None:
        completed = subprocess.run(
            ["bash", "-n", str(DASHBOARD_CATALOG)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
