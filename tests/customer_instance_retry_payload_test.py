#!/usr/bin/env python3
"""Regression coverage for customer provisioning retry payload compatibility."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "dashboard" / "customer_instance_creation.py"
FRONTEND = ROOT / "dashboard" / "web" / "customer-instance.js"


def test_retry_endpoint_accepts_customer_workspace_instance_key() -> None:
    source = BACKEND.read_text(encoding="utf-8")
    assert 'body.get("instance_id") or body.get("instance")' in source


def test_customer_workspace_retry_still_targets_retry_endpoint() -> None:
    source = FRONTEND.read_text(encoding="utf-8")
    assert '"/api/instance/provision/retry"' in source
    assert "async function retryProvision()" in source


if __name__ == "__main__":
    test_retry_endpoint_accepts_customer_workspace_instance_key()
    test_customer_workspace_retry_still_targets_retry_endpoint()
    print("customer instance retry payload regression: OK")
