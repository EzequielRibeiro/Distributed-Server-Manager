#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "${ROOT}/tests/admin_cli_routing_test.sh"
python3 "${ROOT}/tests/admin_cli_port_migration_test.py"
python3 "${ROOT}/tests/admin_management_repository_test.py"
python3 "${ROOT}/tests/customer_admin_c1_c5_test.py"
