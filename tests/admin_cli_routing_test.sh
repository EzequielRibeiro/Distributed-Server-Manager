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

echo "admin_cli_routing_test: ok"
