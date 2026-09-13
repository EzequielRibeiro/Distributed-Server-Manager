#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "dashboard/api/catalog.sh"

class CatalogVersionRecommendationTest(unittest.TestCase):
    def test_first_resolvable_version_is_recommended(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime_dir = root / "catalog/v2/games/minecraft/runtimes"
            resolver_dir = root / "installer/version_resolvers"
            runtime_dir.mkdir(parents=True)
            resolver_dir.mkdir(parents=True)
            (root / "installer/catalog.sh").write_text("#!/usr/bin/env bash\nexit 2\n")
            (root / "installer/catalog_paths.sh").write_text((ROOT / "installer/catalog_paths.sh").read_text())
            runtime = {"id":"minecraft.fake","game":"minecraft","variant":"fake","version":{"strategy":"dynamic","resolver":"fake"}}
            (runtime_dir / "fake.json").write_text(json.dumps(runtime))
            resolver = resolver_dir / "fake.sh"
            resolver.write_text("""#!/usr/bin/env bash
version_resolver_execute() {
  local action="$1" selector="${4:-}"
  case "$action" in
    list) printf '%s\\n' '{"versions":[{"version":"2.0"},{"version":"1.9"}]}' ;;
    resolve) [[ "$selector" == "1.9" ]] && printf '%s\\n' '{"version":"1.9","build":"42"}' || { printf '%s\\n' '{"error":"build_not_found"}'; return 1; } ;;
    *) return 2 ;;
  esac
}
""")
            env = dict(os.environ, DSM_ROOT=str(root))
            result = subprocess.run([str(CATALOG),"versions","minecraft.fake"],env=env,text=True,capture_output=True)
            self.assertEqual(0,result.returncode,result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(["1.9"],[item["value"] for item in payload if item["recommended"]])

if __name__ == "__main__": unittest.main()
