#!/usr/bin/env python3
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "installer/version_resolvers/sponge_maven.sh"

class SpongeMavenResolverListTest(unittest.TestCase):
    def test_list_exposes_only_stable_builds_and_newest_versions_first(self):
        script = f'''set -Eeuo pipefail
source "{RESOLVER}"
sponge_versions() {{
cat <<'EOF'
1.12.2-7.1.1-RC123
1.21.1-12.0.2
1.21.10-14.0.0
1.21.1-12.0.3
1.21.10-14.0.1-SNAPSHOT
EOF
}}
version_resolver_execute list minecraft spongevanilla
'''
        result = subprocess.run(["bash","-c",script],text=True,capture_output=True)
        self.assertEqual(0,result.returncode,result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(["1.21.10","1.21.1","1.21.1"],[item["version"] for item in payload["versions"]])
        self.assertEqual(["14.0.0","12.0.2","12.0.3"],[item["build"] for item in payload["versions"]])
        self.assertTrue(all(item["stable"] for item in payload["versions"]))

if __name__ == "__main__": unittest.main()
