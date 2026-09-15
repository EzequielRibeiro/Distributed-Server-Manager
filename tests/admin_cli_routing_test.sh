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

echo "admin_cli_routing_test: ok"
