#!/usr/bin/env python3
"""Regression contracts for dashboard static-file policy."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "dashboard" / "server.py"


def _server_source():
    return SERVER.read_text(encoding="utf-8")


def test_dashboard_components_are_registered_static_files():
    source = _server_source()

    required = (
        '"/components/header.html":',
        '"/components/sidebar.html":',
        '"/components/cards.html":',
        '"/components/alerts.html":',
    )

    for item in required:
        assert item in source


def test_dashboard_runtime_components_are_public_assets():
    source = _server_source()

    required = (
        '"/theme.js",',
        '"/components/header.html",',
        '"/components/sidebar.html",',
        '"/components/cards.html",',
        '"/components/alerts.html",',
    )

    marker = "public_files = {"
    assert marker in source

    public_block = source.split(marker, 1)[1].split("}", 1)[0]

    for item in required:
        assert item in public_block


def test_sensitive_admin_pages_are_not_public_assets():
    source = _server_source()

    marker = "public_files = {"
    assert marker in source

    public_block = source.split(marker, 1)[1].split("}", 1)[0]

    protected = (
        '"/users.html",',
        '"/settings.html",',
        '"/agents.html",',
        '"/console.html",',
    )

    for item in protected:
        assert item not in public_block
