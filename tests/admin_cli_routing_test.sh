#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAP="${ROOT}/bin/cap"

grep -F 'cap customer create' "${CAP}" >/dev/null
grep -F 'cap contract create' "${CAP}" >/dev/null
grep -F 'cap contract delete' "${CAP}" >/dev/null
grep -F 'cap instance create' "${CAP}" >/dev/null
grep -F 'cap instance delete' "${CAP}" >/dev/null
grep -F 'database/customer_cli.py' "${CAP}" >/dev/null
grep -F 'database/contract_cli.py' "${CAP}" >/dev/null
grep -F 'database/instance_admin_cli.py' "${CAP}" >/dev/null
grep -F 'occupied_ports_provider_for_backend' "${ROOT}/database/instance_admin_cli.py" >/dev/null
grep -F 'resolve_customer_reference(customer_reference, public_only=True)' "${ROOT}/database/instance_admin_cli.py" >/dev/null
grep -F 'customer_code": customer_reference.upper()' "${ROOT}/database/instance_admin_cli.py" >/dev/null
grep -F "role='customer' AND customer_id=" "${ROOT}/database/instance_admin_cli.py" >/dev/null
grep -F '"--json", "runtime", "prepare"' "${ROOT}/database/instance_admin_cli.py" >/dev/null
grep -F 'return "latest"' "${ROOT}/database/instance_admin_cli.py" >/dev/null
grep -F 'resolved HTTP runtime selection has no artifact URL' "${ROOT}/database/instance_admin_cli.py" >/dev/null
grep -F 'from catalog_provisioning_resolver import resolve_catalog_provisioning' "${ROOT}/database/instance_admin_cli.py" >/dev/null
grep -F 'selection, configuration = resolve_catalog_provisioning(' "${ROOT}/database/instance_admin_cli.py" >/dev/null
grep -F 'configuration=configuration' "${ROOT}/database/instance_admin_cli.py" >/dev/null
! grep -F "role='customer' AND scope_id=" "${ROOT}/database/instance_admin_cli.py" >/dev/null
! grep -F 'network.get("source") != "ss"' "${ROOT}/database/instance_admin_cli.py" >/dev/null

bash -n "${CAP}"
python3 -m py_compile \
  "${ROOT}/database/admin_cli_auth.py" \
  "${ROOT}/database/admin_management_repository.py" \
  "${ROOT}/database/customer_cli.py" \
  "${ROOT}/database/contract_cli.py" \
  "${ROOT}/database/instance_admin_cli.py" \
  "${ROOT}/database/agent_instance_runtime_repository.py" \
  "${ROOT}/dashboard/placement_service.py" \
  "${ROOT}/agents/linux/runtime/instance_runtime.py"

python3 - <<'PY' "${ROOT}"
import importlib.util
import json
import pathlib
import sys
from unittest.mock import patch

root = pathlib.Path(sys.argv[1])
sys.path[:0] = [str(root), str(root / "database"), str(root / "dashboard")]
spec = importlib.util.spec_from_file_location("instance_admin_cli", root / "database" / "instance_admin_cli.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

definition = {
    "id": "minecraft.bedrock.vanilla",
    "game": "minecraft",
    "edition": "bedrock",
    "variant": "bedrock",
    "version": {"strategy": "dynamic", "resolver": "minecraft_bedrock"},
}
assert module._runtime_selector(definition) == "latest"
resolved = {
    "kind": "RuntimeSelection",
    "runtime_definition": "minecraft.bedrock.vanilla",
    "game": "minecraft",
    "version": "1.26.45.1",
    "build": "1.26.45.1",
    "provider": "http-archive",
    "asset": {"name": "bedrock.zip", "url": "https://example.invalid/bedrock.zip"},
    "install": {"url": "https://example.invalid/bedrock.zip", "archive_type": "zip"},
}
class Completed:
    returncode = 0
    stdout = json.dumps(resolved)
    stderr = ""
with patch.object(module.subprocess, "run", return_value=Completed()) as run:
    selection = module._content_selection(definition, "latest")
    assert selection["asset"]["url"].startswith("https://")
    assert run.call_args.args[0][-2:] == ["minecraft.bedrock.vanilla", "latest"]

selection, configuration = module.resolve_catalog_provisioning(
    environment_id="minecraft.bedrock.vanilla",
    selector="latest",
    selection=resolved,
    configuration=module._configuration(definition),
    root=root,
)
assert configuration["catalog_runtime_policy"]["runtime_id"] == "minecraft.bedrock.vanilla"
assert configuration["catalog_runtime_policy"]["network_exposure"]
assert configuration["catalog_runtime_id"] == "minecraft.bedrock.vanilla"
assert configuration["catalog_game_id"] == "minecraft"
PY

echo "admin_cli_routing_test: ok"
