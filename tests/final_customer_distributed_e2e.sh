#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT:$ROOT/database:$ROOT/dashboard:$ROOT/agents/linux/runtime${PYTHONPATH:+:$PYTHONPATH}"

# This gate composes the canonical regressions for the completed Customer and
# distributed-operation capabilities. It intentionally keeps external services
# deterministic: the underlying tests use local/fake transports and the Phase 22
# deterministic provisioner rather than live SMTP/Steam/network dependencies.
python3 -m unittest \
  tests/customer_self_service_profile_test.py \
  tests/customer_email_change_test.py \
  tests/customer_geographic_placement_test.py \
  tests/customer_health_alerting_test.py \
  tests/agent_queue_observability_test.py \
  tests/agent_storage_pool_admin_test.py \
  tests/agent_link_recovery_e2e_test.py \
  tests/customer_workspace_architecture_boundary_test.py \
  tests/phase22_customer_dayz_regression_test.py

# Cross-layer privacy guard: Customer-facing regressions must remain responsible
# for proving that physical Agent/Node/fingerprint/path details are not returned.
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
