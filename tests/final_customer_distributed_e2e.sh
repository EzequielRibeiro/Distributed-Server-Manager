#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT:$ROOT/database:$ROOT/dashboard:$ROOT/agents/linux/runtime${PYTHONPATH:+:$PYTHONPATH}"

# Compose the canonical regressions as one gate while preserving process
# isolation between suites. Some legacy tests intentionally monkey-patch process
# globals and are safe individually but must not leak state into the next suite.
tests=(
  tests/customer_self_service_profile_test.py
  tests/customer_email_change_test.py
  tests/customer_geographic_placement_test.py
  tests/customer_health_alerting_test.py
  tests/agent_queue_observability_test.py
  tests/agent_storage_pool_admin_test.py
  tests/agent_link_recovery_e2e_test.py
  tests/customer_workspace_architecture_boundary_test.py
  tests/phase22_customer_dayz_regression_test.py
)

for test_file in "${tests[@]}"; do
  echo "===== Final E2E: ${test_file} ====="
  python3 -m unittest "$test_file"
done

# Cross-layer privacy/correlation guard: the canonical regressions themselves
# must continue to carry assertions for these contracts.
python3 - <<'PY'
from pathlib import Path

required = {
    "tests/customer_geographic_placement_test.py": (
        "agent_id",
        "node_id",
        "fingerprint",
    ),
    "tests/customer_workspace_architecture_boundary_test.py": (
        "Controller",
        "Agent",
    ),
    "tests/customer_health_alerting_test.py": (
        "correlation",
    ),
    "tests/agent_queue_observability_test.py": (
        "retry",
    ),
}

for path, markers in required.items():
    text = Path(path).read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker.lower() not in text.lower()]
    if missing:
        raise SystemExit(f"{path}: integrated contract markers missing: {missing}")

print("Final Customer/distributed E2E contract manifest: OK")
PY
