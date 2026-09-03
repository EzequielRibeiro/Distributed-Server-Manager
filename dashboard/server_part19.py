#!/usr/bin/env python3
"""Canonical runtime secret transport composition layer."""
from __future__ import annotations
from pathlib import Path
import server_part18 as integration
from runtime_secret_http import install_runtime_secret_http
from runtime_secret_integration import install_runtime_secret_transport

legacy = integration.legacy
_ROOT = Path(__file__).resolve().parents[1]
install_runtime_secret_transport()
install_runtime_secret_http(legacy, integration.integration._controller_authenticate, _ROOT)

def run():
    integration.run()

if __name__ == "__main__":
    run()
