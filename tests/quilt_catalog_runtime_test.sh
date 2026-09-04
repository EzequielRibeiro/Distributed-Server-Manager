#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

source "${ROOT}/installer/version_resolvers/quilt_meta.sh"
quilt_get()
{
  case "$1" in
    */versions/game)
      cat <<'JSON'
[{"version":"26.2","stable":true},{"version":"26.3-snapshot-1","stable":false},{"version":"1.21.11","stable":true}]
JSON
      ;;
    */versions/installer)
      cat <<'JSON'
[{"version":"0.15.1","url":"https://maven.quiltmc.org/repository/release/org/quiltmc/quilt-installer/0.15.1/quilt-installer-0.15.1.jar","file_size":8734533,"hashes":{"sha256":"2bd88a1429eaeb3ce3f5e9c49c591c551012937b35bf332ca277b4d93d70408d"}}]
JSON
      ;;
    *) return 1 ;;
  esac
}
GAME_ID=minecraft
VARIANT_ID=quilt
LIST="$(version_resolver_execute list minecraft quilt '')"
jq -e '.versions|map(.version)==["26.2","1.21.11"]' <<<"${LIST}" >/dev/null
RESOLVED="$(version_resolver_execute resolve minecraft quilt '26.2')"
jq -e '.version=="26.2" and .build=="0.15.1" and .selected_asset.name=="quilt-installer.jar" and .install.asset=="quilt-installer.jar" and .install.sha256=="2bd88a1429eaeb3ce3f5e9c49c591c551012937b35bf332ca277b4d93d70408d"' <<<"${RESOLVED}" >/dev/null
if version_resolver_execute resolve minecraft quilt '26.3-snapshot-1' >/dev/null 2>&1; then
  echo "FAIL: unstable Quilt game version accepted" >&2; exit 1
fi

python3 - "${ROOT}" <<'PY'
import importlib.util
import pathlib
import tempfile
from unittest.mock import patch
import sys

root=pathlib.Path(sys.argv[1])
for platform in ("linux","windows"):
    path=root/"agents"/platform/"runtime"/"game_data_installer.py"
    spec=importlib.util.spec_from_file_location(f"quilt_installer_{platform}", path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as td:
        target=pathlib.Path(td)
        (target/"quilt-installer.jar").write_bytes(b"jar")
        selection={
            "version":"26.2",
            "asset":{"name":"quilt-installer.jar"},
            "installer":{"type":"quilt_server","artifact":"quilt-installer.jar","args":[],"timeout_seconds":1200,"expected_outputs":["quilt-server-launch.jar"]},
        }
        java="C:/Java/bin/java.exe" if platform=="windows" else "/usr/bin/java"
        with patch.object(module.shutil,"which",side_effect=lambda name: java if name in ("java","java.exe") else None):
            argv, timeout, expected, _=module.validate_installer(selection,target)
        assert argv[-5:]==["install","server","26.2","--download-server","--install-dir=."]
        assert argv[1]=="-jar" and argv[2].endswith("quilt-installer.jar")
        assert timeout==1200 and expected[0].name=="quilt-server-launch.jar"
        bad={**selection,"installer":{**selection["installer"],"args":["--evil"]}}
        try:
            with patch.object(module.shutil,"which",return_value=java): module.validate_installer(bad,target)
        except ValueError:
            pass
        else:
            raise AssertionError("Quilt accepted catalog-provided arbitrary args")
print("Typed Quilt installer parity passed.")
PY

jq -e '.id=="minecraft.java.quilt" and .version.resolver=="quilt_meta" and .process.executable=="@java" and .process.args==["-jar","quilt-server-launch.jar","nogui"] and .installation.installer.type=="quilt_server"' \
  "${ROOT}/catalog/v2/games/minecraft/runtimes/java-quilt.json" >/dev/null

echo "Quilt catalog runtime tests passed."
