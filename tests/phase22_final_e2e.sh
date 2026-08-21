#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

run_py() {
    local label="$1"
    shift
    printf '\n===== PHASE 22: %s =====\n' "${label}"
    python3 -m unittest "$@"
}

printf '===== CAPIVARA DSM - PHASE 22 FINAL E2E =====\n'

run_py "Fresh Controller / Fresh Agent / Fresh Hybrid" \
    tests/profile_bootstrap_test.py

run_py "Remote Agent / GitHub installation / authenticated heartbeat" \
    tests/phase11_linux_agent_test.py

printf '\n===== PHASE 22: Offline installation / immutable Agent package =====\n'
bash tests/agent_package_test.sh

run_py "Agent pairing / expired token / reused token" \
    tests/agent_secure_pairing_test.py

run_py "Region / Datacenter / Agent installation tracking" \
    tests/phase14_15_agent_dashboard_test.py

run_py "Agent offline / heartbeat-aware placement" \
    tests/agent_heartbeat_placement_test.py

run_py "Agent without location / safe placement failure" \
    tests/placement_unavailable_test.py

run_py "Agent without ports / capabilities / placement" \
    tests/phase16_17_placement_eligibility_test.py

run_py "Upgrade Agent / sequential rollout health verification" \
    tests/phase18_agent_updates_test.py

run_py "Reinstall / restore / orphan / topology reconciliation" \
    tests/phase20_infrastructure_doctor_test.py

run_py "Customer contract / Create DayZ / ports / provision / progress / Controller restart / HTTP regression" \
    tests/phase22_customer_dayz_regression_test.py

run_py "Admin-only instance and cascading contract deletion" \
    tests/admin_destructive_cli_test.py

run_py "Agent-confirmed runtime removal" \
    tests/agent_instance_remove_test.py

printf '\n===== PHASE 22 FINAL E2E: PASS =====\n'
