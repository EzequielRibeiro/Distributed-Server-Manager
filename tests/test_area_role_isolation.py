#!/usr/bin/env python3
"""Regression contract for strict dashboard area isolation."""
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "dashboard" / "server_part8.py").read_text(encoding="utf-8")


def test_customer_pages_are_server_side_protected():
    assert 'CUSTOMER_PROTECTED_PAGES={"/customer.html","/customer-instance.html","/customer-members.html"}' in SOURCE
    assert '_require_area_role(self,user,{"customer"})' in SOURCE


def test_controller_pages_are_server_side_protected():
    assert 'CONTROLLER_PROTECTED_PAGES={"/","/index.html","/console.html","/settings.html","/users.html","/agents.html","/contract-demo.html"}' in SOURCE
    assert '_require_area_role(self,user,{"admin","controller","operator"})' in SOURCE


def test_customer_apis_reject_admin_controller_sessions():
    # All authenticated customer GET/POST dispatches pass through the customer-only role gate.
    assert SOURCE.count('_require_area_role(self,user,{"customer"})') >= 4


def test_area_gate_distinguishes_unauthenticated_from_wrong_role():
    assert 'handler.unauthorized();return False' in SOURCE
    assert 'handler.forbidden();return False' in SOURCE
